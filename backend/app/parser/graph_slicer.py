"""Graph analysis, entry point detection, topological ordering, and 1-hop slicing."""
from __future__ import annotations

import networkx as nx

from app.models.ir import (
    CallEdge,
    CallableNode,
    ContainerNode,
    DataFlowEdge,
    DependencyNode,
    IRSlice,
    ProgramIR,
    TypeRelationEdge,
    VariableNode,
)


class GraphSlicer:
    """Uses NetworkX to analyze IR call and dependency graphs and perform 1-hop slicing."""

    def __init__(self, ir: ProgramIR) -> None:
        self.ir = ir
        self.call_graph = nx.DiGraph()
        self.full_graph = nx.DiGraph()
        self._build_graphs()

    def _build_graphs(self) -> None:
        # Add callables to call_graph
        for c in self.ir.symbols.callables:
            self.call_graph.add_node(c.id, kind="callable", node=c)
            self.full_graph.add_node(c.id, kind="callable", node=c)

        # Add containers
        for ct in self.ir.symbols.containers:
            self.full_graph.add_node(ct.id, kind="container", node=ct)

        # Add variables
        for v in self.ir.symbols.variables:
            self.full_graph.add_node(v.id, kind="variable", node=v)

        # Add dependencies
        for d in self.ir.dependencies:
            self.full_graph.add_node(d.id, kind="dependency", node=d)

        # Add call edges
        for call in self.ir.edges.calls:
            self.full_graph.add_edge(call.source_id, call.target_id, kind="call", edge=call)
            if self.call_graph.has_node(call.source_id) and self.call_graph.has_node(call.target_id):
                self.call_graph.add_edge(call.source_id, call.target_id, edge=call)

        # Add data flow edges
        for df in self.ir.edges.data_flows:
            self.full_graph.add_edge(df.source_id, df.target_id, kind="data_flow", edge=df)

        # Add type relations
        for tr in self.ir.edges.type_relations:
            self.full_graph.add_edge(tr.source_id, tr.target_id, kind="type_relation", edge=tr)

    def compute_entry_points(self) -> list[str]:
        """Find root callables that act as entry points."""
        entry_points: list[str] = []
        callables = self.ir.symbols.callables
        if not callables:
            return []

        # Priority 1: Common entry function names
        common_names = {"main", "run", "handler", "start", "execute", "index", "init"}
        for c in callables:
            if c.name.lower() in common_names and c.kind == "function":
                entry_points.append(c.id)

        # Priority 2: In-degree 0 in internal call graph (functions not called by other functions)
        for c in callables:
            if c.id not in entry_points:
                in_degree = self.call_graph.in_degree(c.id) if self.call_graph.has_node(c.id) else 0
                if in_degree == 0:
                    entry_points.append(c.id)

        # Fallback: if all have callers (cycle) or none matched, use the first callable
        if not entry_points and callables:
            entry_points.append(callables[0].id)

        return entry_points

    def compute_topological_order(self) -> list[str]:
        """Compute execution order using topological sort or cycle condensation."""
        if not self.call_graph.nodes:
            return []

        try:
            # Check if DAG
            if nx.is_directed_acyclic_graph(self.call_graph):
                return list(nx.topological_sort(self.call_graph))
            else:
                # Condense SCCs into a DAG and order components
                condensed = nx.condensation(self.call_graph)
                ordered: list[str] = []
                for scc_idx in nx.topological_sort(condensed):
                    members = condensed.nodes[scc_idx]["members"]
                    ordered.extend(members)
                return ordered
        except Exception:
            # Fallback to node insertion order
            return list(self.call_graph.nodes)

    def extract_1hop_slice(self, target_symbol_id: str | None = None) -> IRSlice:
        """Extract target callable, immediate 1-hop upstream/downstream neighbors, and incident edges."""
        callables = self.ir.symbols.callables
        if not callables:
            raise ValueError("No callables found in ProgramIR to slice")

        # Resolve target symbol ID
        target_id = target_symbol_id
        if not target_id:
            entry_points = self.compute_entry_points()
            target_id = entry_points[0] if entry_points else callables[0].id

        target_node = next((c for c in callables if c.id == target_id), None)
        if not target_node:
            # If target_id didn't match directly, try matching by name
            target_node = next((c for c in callables if c.name == target_id or c.qualname == target_id), None)
            if target_node:
                target_id = target_node.id
            else:
                raise ValueError(f"Callable '{target_id}' not found")

        # 1-hop callers (upstream) and callees (downstream)
        upstream_ids = set()
        downstream_ids = set()

        if self.call_graph.has_node(target_id):
            upstream_ids = set(self.call_graph.predecessors(target_id))
            downstream_ids = set(self.call_graph.successors(target_id))

        upstream_callables = [c for c in callables if c.id in upstream_ids]
        downstream_callables = [c for c in callables if c.id in downstream_ids]

        # Connected containers
        related_container_ids = set()
        if target_node.container_id:
            related_container_ids.add(target_node.container_id)
        for c in upstream_callables + downstream_callables:
            if c.container_id:
                related_container_ids.add(c.container_id)

        related_containers = [ct for ct in self.ir.symbols.containers if ct.id in related_container_ids]

        # Scope IDs for edge and variable filtering
        scoped_symbol_ids = {target_id} | upstream_ids | downstream_ids | related_container_ids

        # Relevant calls
        relevant_calls: list[CallEdge] = []
        for call in self.ir.edges.calls:
            if call.source_id == target_id or call.target_id == target_id:
                relevant_calls.append(call)

        # Relevant dependencies
        referenced_dep_ids = {call.target_id for call in relevant_calls if call.target_id.startswith("dep:")}
        relevant_deps = [d for d in self.ir.dependencies if d.id in referenced_dep_ids or d.module_id == target_node.module_id]

        # Relevant variables (parameters, fields, locals of target and neighbors)
        relevant_vars = [
            v for v in self.ir.symbols.variables
            if v.owner_id in scoped_symbol_ids or v.id in scoped_symbol_ids
        ]
        scoped_var_ids = {v.id for v in relevant_vars}
        all_scoped_ids = scoped_symbol_ids | scoped_var_ids

        # Relevant data flows
        relevant_df = [
            df for df in self.ir.edges.data_flows
            if df.source_id in all_scoped_ids and df.target_id in all_scoped_ids
        ]

        # Relevant type relations
        relevant_tr = [
            tr for tr in self.ir.edges.type_relations
            if tr.source_id in related_container_ids
        ]

        return IRSlice(
            analysis_id=self.ir.analysis_id,
            target_symbol_id=target_id,
            primary_language=self.ir.metadata.primary_language,
            runtime_paradigm=self.ir.metadata.runtime_paradigm,
            target_callable=target_node,
            upstream_callables=upstream_callables,
            downstream_callables=downstream_callables,
            related_containers=related_containers,
            dependencies=relevant_deps,
            variables=relevant_vars,
            calls=relevant_calls,
            data_flows=relevant_df,
            type_relations=relevant_tr,
        )

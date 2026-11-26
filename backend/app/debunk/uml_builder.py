"""UML diagram builder — transforms ProgramIR into React Flow + ELKjs node/edge payloads."""
from __future__ import annotations

from app.models.ir import ProgramIR, IRSlice
from app.models.uml import UMLDiagram, UMLEdge, UMLEdgeData, UMLNode, UMLNodeData


def _complete_endpoints(nodes: list[UMLNode], edges: list[UMLEdge]) -> None:
    """Represent unresolved/builtin boundaries at the exact referring source span."""
    known = {node.id for node in nodes}
    for edge in edges:
        for endpoint in (edge.source, edge.target):
            if endpoint not in known:
                source_id = endpoint.removeprefix("node:")
                nodes.append(UMLNode(
                    id=endpoint, source_id=source_id,
                    data=UMLNodeData(
                        label=source_id.split(":")[-1], kind="external",
                        span=edge.data.span, extra={"unresolved": True},
                    ),
                ))
                known.add(endpoint)


def build_class_diagram(ir: ProgramIR) -> UMLDiagram:
    """Build a UML Class & Component diagram from the full ProgramIR."""
    nodes: list[UMLNode] = []
    edges: list[UMLEdge] = []

    # Container nodes (classes / interfaces)
    for ct in ir.symbols.containers:
        nodes.append(UMLNode(
            id=f"node:{ct.id}",
            data=UMLNodeData(
                label=ct.name,
                kind="container",
                span=ct.span,
                extra={
                    "kind": ct.kind,
                    "bases": ct.bases,
                    "field_count": len(ct.field_ids),
                    "method_count": len(ct.method_ids),
                }
            ),
            source_id=ct.id,
        ))

    # Callable nodes (functions / methods)
    for c in ir.symbols.callables:
        nodes.append(UMLNode(
            id=f"node:{c.id}",
            data=UMLNodeData(
                label=c.qualname,
                kind="callable",
                span=c.span,
                extra={
                    "kind": c.kind,
                    "purity": c.purity,
                    "is_async": c.is_async,
                    "params": [{"name": p.name, "type": p.declared_type} for p in c.parameters],
                    "return_type": c.return_type,
                    "container_id": c.container_id,
                }
            ),
            source_id=c.id,
        ))

    # Dependency boundary nodes
    seen_deps: set[str] = set()
    for dep in ir.dependencies:
        if dep.id not in seen_deps:
            seen_deps.add(dep.id)
            nodes.append(UMLNode(
                id=f"node:{dep.id}",
                data=UMLNodeData(
                    label=dep.name,
                    kind="dependency",
                    span=dep.span,
                    extra={
                        "category": dep.category,
                        "imported_symbols": dep.imported_symbols,
                        "alias": dep.alias,
                    }
                ),
                source_id=dep.id,
            ))

    # Type relation edges (inherits / implements / composes)
    for tr in ir.edges.type_relations:
        edges.append(UMLEdge(
            id=f"uml:{tr.id}",
            source=f"node:{tr.source_id}",
            target=f"node:{tr.target_id}",
            data=UMLEdgeData(label=tr.relation, kind="type_relation", span=tr.span),
            source_edge_id=tr.id,
        ))

    # Call edges
    for call in ir.edges.calls:
        edges.append(UMLEdge(
            id=f"uml:{call.id}",
            source=f"node:{call.source_id}",
            target=f"node:{call.target_id}",
            animated=False,
            data=UMLEdgeData(
                label=f"calls {call.target_name}",
                kind="call",
                span=call.span,
                sequence_order=call.sequence_order,
            ),
            source_edge_id=call.id,
        ))

    _complete_endpoints(nodes, edges)
    return UMLDiagram(view="class", nodes=nodes, edges=edges)


def build_dataflow_diagram(ir_slice: IRSlice) -> UMLDiagram:
    """Build a Data-Flow & Sequence pipeline diagram from a 1-hop IR slice."""
    nodes: list[UMLNode] = []
    edges: list[UMLEdge] = []

    # Collect all callables involved in the slice
    all_callables = (
        [ir_slice.target_callable]
        + ir_slice.upstream_callables
        + ir_slice.downstream_callables
    )

    for c in {c.id: c for c in all_callables}.values():
        nodes.append(UMLNode(
            id=f"node:{c.id}",
            data=UMLNodeData(
                label=c.qualname,
                kind="callable",
                span=c.span,
                extra={
                    "is_target": c.id == ir_slice.target_symbol_id,
                    "kind": c.kind,
                    "params": [{"name": p.name, "type": p.declared_type} for p in c.parameters],
                    "return_type": c.return_type,
                }
            ),
            source_id=c.id,
        ))

    # Include locals and dependencies too: data-flow edges refer to these nodes.
    for v in ir_slice.variables:
        nodes.append(UMLNode(
            id=f"node:{v.id}",
            data=UMLNodeData(
                label=f"{v.name}: {v.declared_type or v.inferred_shape or 'Any'}",
                kind="variable",
                span=v.span,
                extra={"scope": v.scope, "shape": v.inferred_shape, "default": v.default_value}
            ),
            source_id=v.id,
        ))

    for dep in ir_slice.dependencies:
        nodes.append(UMLNode(
            id=f"node:{dep.id}", source_id=dep.id,
            data=UMLNodeData(label=dep.name, kind="dependency", span=dep.span,
                             extra={"category": dep.category}),
        ))

    # Data flow edges (numbered by step)
    for df in sorted(ir_slice.data_flows, key=lambda d: d.step):
        edges.append(UMLEdge(
            id=f"uml:{df.id}",
            source=f"node:{df.source_id}",
            target=f"node:{df.target_id}",
            animated=True,
            data=UMLEdgeData(
                label=df.transformation_summary[:50],
                kind="data_flow",
                span=df.span,
                step=df.step,
            ),
            source_edge_id=df.id,
        ))

    # Call edges within the slice
    for call in sorted(ir_slice.calls, key=lambda c: c.sequence_order):
        edges.append(UMLEdge(
            id=f"uml:{call.id}",
            source=f"node:{call.source_id}",
            target=f"node:{call.target_id}",
            animated=False,
            data=UMLEdgeData(
                label=f"[{call.sequence_order}] {call.target_name}({', '.join(call.arguments[:2])})",
                kind="call",
                span=call.span,
                sequence_order=call.sequence_order,
            ),
            source_edge_id=call.id,
        ))

    _complete_endpoints(nodes, edges)
    return UMLDiagram(view="dataflow", nodes=nodes, edges=edges)

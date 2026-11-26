"""Deterministic AST extractor for Python source code using Tree-sitter."""
from __future__ import annotations

from typing import Any
from tree_sitter import Node, Tree

from app.models.ir import (
    CallEdge,
    CallableKind,
    CallableNode,
    ContainerKind,
    ContainerNode,
    DataFlowEdge,
    DependencyCategory,
    DependencyNode,
    EdgesCollection,
    ModuleNode,
    ParameterInfo,
    Purity,
    SourceSpan,
    SymbolsCollection,
    TypeRelationEdge,
    VariableNode,
    VariableScope,
)
from app.parser.base import (
    classify_python_dependency,
    make_callable_id,
    make_container_id,
    make_dep_id,
    make_module_id,
    make_param_id,
    make_variable_id,
    node_text,
    sanitize_id_part,
    to_source_span,
)


class PythonExtractor:
    """Extracts symbols, dependencies, and edges from Python Tree-sitter AST."""

    def __init__(self, source_code: str, file_path: str = "main.py") -> None:
        self.source_code = source_code
        self.source_bytes = source_code.encode("utf-8")
        self.file_path = file_path
        self.module_id = make_module_id(file_path)

        self.modules: list[ModuleNode] = []
        self.dependencies: list[DependencyNode] = []
        self.containers: list[ContainerNode] = []
        self.callables: list[CallableNode] = []
        self.variables: list[VariableNode] = []

        self.calls: list[CallEdge] = []
        self.data_flows: list[DataFlowEdge] = []
        self.type_relations: list[TypeRelationEdge] = []

        self._call_counter = 0
        self._df_counter = 0
        self._tr_counter = 0

        # Fast lookup by symbol name for edge resolution
        self._callable_by_name: dict[str, str] = {}
        self._dep_by_symbol: dict[str, str] = {}

    def extract(self, tree: Tree) -> tuple[list[ModuleNode], list[DependencyNode], SymbolsCollection, EdgesCollection]:
        root = tree.root_node
        line_count = len(self.source_code.splitlines())
        root_span = to_source_span(root, self.source_bytes)
        if root_span.end_line < line_count:
            root_span.end_line = line_count

        module_node = ModuleNode(
            id=self.module_id,
            path=self.file_path,
            language="python",
            line_count=line_count,
            span=root_span,
        )
        self.modules.append(module_node)

        # 1. First pass: extract imports and top-level definitions
        for child in root.children:
            if child.type == "decorated_definition":
                child = child.child_by_field_name("definition") or child
            if child.type in ("import_statement", "import_from_statement"):
                self._extract_import(child)
            elif child.type == "class_definition":
                self._extract_class(child)
            elif child.type == "function_definition":
                self._extract_function(child, container_id=None, prefix="")
            elif child.type == "expression_statement":
                # Check top-level assignments
                for expr_child in child.children:
                    if expr_child.type == "assignment":
                        self._extract_assignment(expr_child, scope="global", owner_id=None)

        # 2. Second pass: resolve call targets and data flow
        self._resolve_call_targets()

        symbols = SymbolsCollection(
            containers=self.containers,
            callables=self.callables,
            variables=self.variables,
        )
        edges = EdgesCollection(
            calls=self.calls,
            data_flows=self.data_flows,
            type_relations=self.type_relations,
        )

        return self.modules, self.dependencies, symbols, edges

    def _extract_import(self, node: Node) -> None:
        span = to_source_span(node, self.source_bytes)
        if node.type == "import_statement":
            # e.g. import math, os as operating_system
            for child in node.children:
                if child.type == "dotted_name":
                    name = node_text(child, self.source_bytes)
                    dep_id = make_dep_id(self.module_id, name, span.start_line)
                    category = classify_python_dependency(name)
                    dep = DependencyNode(
                        id=dep_id,
                        name=name,
                        category=category,
                        module_id=self.module_id,
                        span=span,
                    )
                    self.dependencies.append(dep)
                    self._dep_by_symbol[name] = dep_id
                elif child.type == "aliased_import":
                    # dotted_name as alias
                    orig_node = child.child_by_field_name("name")
                    alias_node = child.child_by_field_name("alias")
                    if orig_node:
                        orig_name = node_text(orig_node, self.source_bytes)
                        alias_name = node_text(alias_node, self.source_bytes) if alias_node else None
                        dep_id = make_dep_id(self.module_id, orig_name, span.start_line)
                        dep = DependencyNode(
                            id=dep_id,
                            name=orig_name,
                            alias=alias_name,
                            category=classify_python_dependency(orig_name),
                            module_id=self.module_id,
                            span=span,
                        )
                        self.dependencies.append(dep)
                        if alias_name:
                            self._dep_by_symbol[alias_name] = dep_id
                        self._dep_by_symbol[orig_name] = dep_id

        elif node.type == "import_from_statement":
            # e.g. from math import sqrt, ceil as c
            module_name_node = node.child_by_field_name("module_name")
            mod_name = node_text(module_name_node, self.source_bytes) if module_name_node else ""
            imported_symbols: list[str] = []
            dep_id = make_dep_id(self.module_id, mod_name or "unknown", span.start_line)

            for child in node.children:
                if child.type == "dotted_name" and child != module_name_node:
                    sym_name = node_text(child, self.source_bytes)
                    imported_symbols.append(sym_name)
                    self._dep_by_symbol[sym_name] = dep_id
                elif child.type == "aliased_import":
                    orig_n = child.child_by_field_name("name")
                    alias_n = child.child_by_field_name("alias")
                    if orig_n:
                        sym_name = node_text(orig_n, self.source_bytes)
                        alias_name = node_text(alias_n, self.source_bytes) if alias_n else None
                        imported_symbols.append(alias_name or sym_name)
                        if alias_name:
                            self._dep_by_symbol[alias_name] = dep_id
                        self._dep_by_symbol[sym_name] = dep_id

            dep = DependencyNode(
                id=dep_id,
                name=mod_name or "relative",
                imported_symbols=imported_symbols,
                category=classify_python_dependency(mod_name),
                module_id=self.module_id,
                span=span,
            )
            self.dependencies.append(dep)

    def _extract_class(self, node: Node) -> None:
        span = to_source_span(node, self.source_bytes)
        name_node = node.child_by_field_name("name")
        class_name = node_text(name_node, self.source_bytes) if name_node else "AnonymousClass"
        container_id = make_container_id(self.module_id, class_name, span.start_line)

        # Superclasses / inheritance
        bases: list[str] = []
        superclasses_node = node.child_by_field_name("superclasses")
        if superclasses_node:
            for child in superclasses_node.children:
                if child.type in ("identifier", "attribute"):
                    base_name = node_text(child, self.source_bytes)
                    bases.append(base_name)
                    self._tr_counter += 1
                    tr_edge = TypeRelationEdge(
                        id=f"edge:tr:{self._tr_counter}",
                        source_id=container_id,
                        target_id=f"sym:container:{self.module_id}:{base_name}:0",
                        target_name=base_name,
                        relation="inherits",
                        span=to_source_span(child, self.source_bytes),
                    )
                    self.type_relations.append(tr_edge)

        method_ids: list[str] = []
        field_ids: list[str] = []

        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                if child.type == "decorated_definition":
                    child = child.child_by_field_name("definition") or child
                if child.type == "function_definition":
                    method = self._extract_function(child, container_id=container_id, prefix=f"{class_name}.")
                    method_ids.append(method.id)
                elif child.type == "expression_statement":
                    for expr_child in child.children:
                        if expr_child.type == "assignment":
                            var_node = self._extract_assignment(expr_child, scope="field", owner_id=container_id)
                            if var_node:
                                field_ids.append(var_node.id)

        container = ContainerNode(
            id=container_id,
            name=class_name,
            kind="class",
            bases=bases,
            field_ids=field_ids,
            method_ids=method_ids,
            module_id=self.module_id,
            span=span,
        )
        self.containers.append(container)

    def _extract_function(self, node: Node, container_id: str | None, prefix: str = "") -> CallableNode:
        span = to_source_span(node, self.source_bytes)
        name_node = node.child_by_field_name("name")
        fn_name = node_text(name_node, self.source_bytes) if name_node else "anonymous"
        qualname = f"{prefix}{fn_name}"
        fn_id = make_callable_id(self.module_id, qualname, span.start_line)
        self._callable_by_name[fn_name] = fn_id
        self._callable_by_name[qualname] = fn_id

        kind: CallableKind = "function"
        if container_id:
            kind = "constructor" if fn_name == "__init__" else "method"

        # Parameters
        parameters: list[ParameterInfo] = []
        params_node = node.child_by_field_name("parameters")
        if params_node:
            for p_child in params_node.children:
                p_info = self._parse_python_param(p_child, qualname)
                if p_info:
                    # Skip 'self' / 'cls' for cleaner user parameter lists
                    if p_info.name in ("self", "cls") and container_id:
                        continue
                    parameters.append(p_info)
                    # Register parameter as VariableNode with scope='parameter'
                    v_node = VariableNode(
                        id=p_info.id,
                        name=p_info.name,
                        scope="parameter",
                        mutability="mutable",
                        declared_type=p_info.declared_type,
                        inferred_shape=p_info.inferred_shape,
                        default_value=p_info.default_value,
                        is_optional=p_info.is_optional,
                        owner_id=fn_id,
                        module_id=self.module_id,
                        span=p_info.span,
                    )
                    self.variables.append(v_node)

        # Return type
        return_type_node = node.child_by_field_name("return_type")
        return_type = node_text(return_type_node, self.source_bytes) if return_type_node else None
        inferred_return_shape = self._infer_shape_from_type_str(return_type) if return_type else None

        # Check async
        is_async = False
        first_child = node.children[0] if node.children else None
        if first_child and first_child.type == "async":
            is_async = True

        # Source excerpt
        source_excerpt = node_text(node, self.source_bytes)

        # Body analysis: calls, local variables, data flows, and purity
        body = node.child_by_field_name("body")
        purity: Purity = "pure"
        if body:
            seq_order = 0
            df_step = 0

            # Initial data flow: parameters feed into function
            for p in parameters:
                df_step += 1
                self._df_counter += 1
                self.data_flows.append(
                    DataFlowEdge(
                        id=f"edge:df:{self._df_counter}",
                        source_id=p.id,
                        target_id=fn_id,
                        variable_name=p.name,
                        step=df_step,
                        transformation_summary=f"Input parameter {p.name} initialized",
                        span=p.span,
                    )
                )

            # Traverse body nodes
            body_text = node_text(body, self.source_bytes)
            # Purity check: standard impure operations
            if any(imp in body_text for imp in ("print(", "open(", "random.", "time.time", "socket.", "subprocess.")):
                purity = "impure"

            for statement in body.children:
                # Find calls
                calls_in_stmt = self._find_nodes_of_type(statement, "call")
                for c_node in calls_in_stmt:
                    seq_order += 1
                    self._call_counter += 1
                    func_target_node = c_node.child_by_field_name("function")
                    args_node = c_node.child_by_field_name("arguments")

                    target_name = node_text(func_target_node, self.source_bytes) if func_target_node else "anonymous"
                    arg_texts = []
                    if args_node:
                        for arg in args_node.children:
                            if arg.type not in ("(", ")", ","):
                                arg_texts.append(node_text(arg, self.source_bytes))

                    call_edge = CallEdge(
                        id=f"edge:call:{self._call_counter}",
                        source_id=fn_id,
                        target_id=target_name,  # Temporary, resolved in second pass
                        target_name=target_name,
                        sequence_order=seq_order,
                        arguments=arg_texts,
                        span=to_source_span(c_node, self.source_bytes),
                    )
                    self.calls.append(call_edge)

                # Find assignments (local variables and def-use flows)
                assignments = self._find_nodes_of_type(statement, "assignment")
                for a_node in assignments:
                    var_node = self._extract_assignment(a_node, scope="local", owner_id=fn_id)
                    if var_node:
                        df_step += 1
                        self._df_counter += 1
                        self.data_flows.append(
                            DataFlowEdge(
                                id=f"edge:df:{self._df_counter}",
                                source_id=fn_id,
                                target_id=var_node.id,
                                variable_name=var_node.name,
                                step=df_step,
                                transformation_summary=f"Assigned local variable {var_node.name}",
                                span=var_node.span,
                            )
                        )

                # Return statement
                if statement.type == "return_statement":
                    ret_expr = statement.children[1] if len(statement.children) > 1 else None
                    if ret_expr:
                        df_step += 1
                        self._df_counter += 1
                        ret_text = node_text(ret_expr, self.source_bytes)
                        self.data_flows.append(
                            DataFlowEdge(
                                id=f"edge:df:{self._df_counter}",
                                source_id=fn_id,
                                target_id=fn_id,
                                variable_name="<return>",
                                step=df_step,
                                transformation_summary=f"Returns: {ret_text[:40]}",
                                span=to_source_span(statement, self.source_bytes),
                            )
                        )

        callable_node = CallableNode(
            id=fn_id,
            name=fn_name,
            qualname=qualname,
            kind=kind,
            parameters=parameters,
            return_type=return_type,
            inferred_return_shape=inferred_return_shape,
            purity=purity,
            is_async=is_async,
            container_id=container_id,
            module_id=self.module_id,
            span=span,
            source_excerpt=source_excerpt,
        )
        self.callables.append(callable_node)
        return callable_node

    def _parse_python_param(self, node: Node, fn_name: str) -> ParameterInfo | None:
        span = to_source_span(node, self.source_bytes)
        name: str | None = None
        declared_type: str | None = None
        default_val: str | None = None
        is_optional: bool = False

        if node.type == "identifier":
            name = node_text(node, self.source_bytes)
        elif node.type == "default_parameter":
            name_n = node.child_by_field_name("name")
            val_n = node.child_by_field_name("value")
            name = node_text(name_n, self.source_bytes) if name_n else None
            default_val = node_text(val_n, self.source_bytes) if val_n else None
            is_optional = True
        elif node.type == "typed_parameter":
            # child: identifier, type
            for c in node.children:
                if c.type == "identifier" and name is None:
                    name = node_text(c, self.source_bytes)
                elif c.type == "type":
                    declared_type = node_text(c, self.source_bytes)
        elif node.type == "typed_default_parameter":
            name_n = node.child_by_field_name("name")
            type_n = node.child_by_field_name("type")
            val_n = node.child_by_field_name("value")
            name = node_text(name_n, self.source_bytes) if name_n else None
            declared_type = node_text(type_n, self.source_bytes) if type_n else None
            default_val = node_text(val_n, self.source_bytes) if val_n else None
            is_optional = True

        if not name or name in (",", "(", ")", "*", "**"):
            return None

        if declared_type and ("Optional" in declared_type or "None" in str(default_val)):
            is_optional = True

        inferred_shape = self._infer_shape_from_type_str(declared_type) if declared_type else "Any"

        return ParameterInfo(
            id=make_param_id(self.module_id, fn_name, name),
            name=name,
            declared_type=declared_type,
            inferred_shape=inferred_shape,
            default_value=default_val,
            is_optional=is_optional,
            span=span,
        )

    def _extract_assignment(self, node: Node, scope: VariableScope, owner_id: str | None) -> VariableNode | None:
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        type_n = node.child_by_field_name("type")

        if not left:
            return None

        var_name = node_text(left, self.source_bytes)
        # Handle self.field
        if var_name.startswith("self."):
            var_name = var_name[5:]
            scope = "field"

        declared_type = node_text(type_n, self.source_bytes) if type_n else None
        default_val = node_text(right, self.source_bytes) if right else None
        inferred_shape = self._infer_shape_from_value_expr(right, declared_type)

        span = to_source_span(node, self.source_bytes)
        var_id = make_variable_id(self.module_id, var_name, span.start_line)

        # Check mutability: UPPERCASE globals are considered immutable constants
        mutability = "immutable" if (scope == "global" and var_name.isupper()) else "mutable"

        var_node = VariableNode(
            id=var_id,
            name=var_name,
            scope=scope,
            mutability=mutability,
            declared_type=declared_type,
            inferred_shape=inferred_shape,
            default_value=default_val,
            is_optional=False,
            owner_id=owner_id,
            module_id=self.module_id,
            span=span,
        )
        self.variables.append(var_node)
        return var_node

    def _infer_shape_from_type_str(self, type_str: str | None) -> str:
        if not type_str:
            return "Any"
        t = type_str.strip()
        if t in ("int", "float", "bool", "str", "bytes"):
            return t
        if t.startswith("list") or t.startswith("List"):
            return "list"
        if t.startswith("dict") or t.startswith("Dict"):
            return "dict"
        if t.startswith("set") or t.startswith("Set"):
            return "set"
        if t.startswith("tuple") or t.startswith("Tuple"):
            return "tuple"
        return t

    def _infer_shape_from_value_expr(self, right_node: Node | None, declared_type: str | None) -> str:
        if declared_type:
            return self._infer_shape_from_type_str(declared_type)
        if not right_node:
            return "unknown"
        if right_node.type == "integer":
            return "int"
        if right_node.type == "float":
            return "float"
        if right_node.type in ("string", "concatenated_string"):
            return "str"
        if right_node.type in ("true", "false"):
            return "bool"
        if right_node.type == "list":
            return "list"
        if right_node.type == "dictionary":
            return "dict"
        if right_node.type == "set":
            return "set"
        if right_node.type == "tuple":
            return "tuple"
        return "Any"

    def _find_nodes_of_type(self, node: Node, target_type: str) -> list[Node]:
        result: list[Node] = []
        if node.type == target_type:
            result.append(node)
        for child in node.children:
            result.extend(self._find_nodes_of_type(child, target_type))
        return result

    def _resolve_call_targets(self) -> None:
        containers_by_name = {container.name: container.id for container in self.containers}
        for call in self.calls:
            tname = call.target_name
            # Direct match to internal callable
            if tname in self._callable_by_name:
                call.target_id = self._callable_by_name[tname]
            elif tname in containers_by_name:
                call.target_id = containers_by_name[tname]
            # Match to imported dependency
            elif tname in self._dep_by_symbol:
                call.target_id = self._dep_by_symbol[tname]
            # Method call on object: e.g. obj.method
            elif "." in tname:
                parts = tname.split(".")
                method_name = parts[-1]
                if method_name in self._callable_by_name:
                    call.target_id = self._callable_by_name[method_name]
                elif parts[0] in self._dep_by_symbol:
                    call.target_id = self._dep_by_symbol[parts[0]]
                else:
                    call.target_id = f"sym:unresolved:{sanitize_id_part(tname)}"
            else:
                call.target_id = f"sym:builtin:{sanitize_id_part(tname)}"

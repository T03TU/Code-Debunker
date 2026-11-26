"""Deterministic AST extractor for JavaScript and TypeScript source code."""
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
    classify_js_dependency,
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


class JsTsExtractor:
    """Extracts symbols, dependencies, and edges from JS/TS Tree-sitter AST."""

    def __init__(self, source_code: str, file_path: str = "index.ts", language: str = "typescript") -> None:
        self.source_code = source_code
        self.source_bytes = source_code.encode("utf-8")
        self.file_path = file_path
        self.language = language
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
            language=self.language,
            line_count=line_count,
            span=root_span,
        )
        self.modules.append(module_node)

        # Traverse root statements
        for child in root.children:
            self._process_root_statement(child)

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

    def _process_root_statement(self, node: Node) -> None:
        # Unwrap export_statement if present
        actual_node = node
        if node.type == "export_statement":
            for child in node.children:
                if child.type in ("function_declaration", "class_declaration", "lexical_declaration", "variable_declaration", "interface_declaration"):
                    actual_node = child
                    break

        if actual_node.type == "import_statement":
            self._extract_import(actual_node)
        elif actual_node.type in ("class_declaration", "interface_declaration"):
            self._extract_class_or_interface(actual_node)
        elif actual_node.type == "function_declaration":
            self._extract_function(actual_node, container_id=None, prefix="")
        elif actual_node.type in ("lexical_declaration", "variable_declaration"):
            self._extract_var_declaration(actual_node, scope="global", owner_id=None)

    def _extract_import(self, node: Node) -> None:
        span = to_source_span(node, self.source_bytes)
        source_n = node.child_by_field_name("source")
        source_text = node_text(source_n, self.source_bytes).strip("'\"") if source_n else ""
        dep_id = make_dep_id(self.module_id, source_text or "unknown", span.start_line)
        category = classify_js_dependency(source_text)

        imported_symbols: list[str] = []
        clause = node.child_by_field_name("import_clause") or node
        for child in self._find_nodes_of_type(clause, "import_specifier"):
            name_n = child.child_by_field_name("name")
            alias_n = child.child_by_field_name("alias")
            sname = node_text(alias_n or name_n or child, self.source_bytes)
            imported_symbols.append(sname)
            self._dep_by_symbol[sname] = dep_id

        dep = DependencyNode(
            id=dep_id,
            name=source_text,
            imported_symbols=imported_symbols,
            category=category,
            module_id=self.module_id,
            span=span,
        )
        self.dependencies.append(dep)

    def _extract_class_or_interface(self, node: Node) -> None:
        span = to_source_span(node, self.source_bytes)
        name_n = node.child_by_field_name("name")
        class_name = node_text(name_n, self.source_bytes) if name_n else "AnonymousClass"
        kind: ContainerKind = "interface" if node.type == "interface_declaration" else "class"
        container_id = make_container_id(self.module_id, class_name, span.start_line)

        bases: list[str] = []
        heritage_nodes = self._find_nodes_of_type(node, "class_heritage")
        for h in heritage_nodes:
            for child in h.children:
                if child.type == "extends_clause":
                    for c in child.children:
                        if c.type in ("identifier", "type_identifier"):
                            base_name = node_text(c, self.source_bytes)
                            bases.append(base_name)
                            self._tr_counter += 1
                            self.type_relations.append(
                                TypeRelationEdge(
                                    id=f"edge:tr:{self._tr_counter}",
                                    source_id=container_id,
                                    target_id=f"sym:container:{self.module_id}:{base_name}:0",
                                    target_name=base_name,
                                    relation="inherits",
                                    span=to_source_span(c, self.source_bytes),
                                )
                            )
                elif child.type == "implements_clause":
                    for c in child.children:
                        if c.type in ("identifier", "type_identifier"):
                            base_name = node_text(c, self.source_bytes)
                            bases.append(base_name)
                            self._tr_counter += 1
                            self.type_relations.append(
                                TypeRelationEdge(
                                    id=f"edge:tr:{self._tr_counter}",
                                    source_id=container_id,
                                    target_id=f"sym:container:{self.module_id}:{base_name}:0",
                                    target_name=base_name,
                                    relation="implements",
                                    span=to_source_span(c, self.source_bytes),
                                )
                            )

        method_ids: list[str] = []
        field_ids: list[str] = []

        body = node.child_by_field_name("body")
        if body:
            for child in body.children:
                if child.type == "method_definition":
                    m = self._extract_method(child, container_id=container_id, class_name=class_name)
                    method_ids.append(m.id)
                elif child.type in ("field_definition", "public_field_definition"):
                    f = self._extract_class_field(child, container_id=container_id)
                    if f:
                        field_ids.append(f.id)

        container = ContainerNode(
            id=container_id,
            name=class_name,
            kind=kind,
            bases=bases,
            field_ids=field_ids,
            method_ids=method_ids,
            module_id=self.module_id,
            span=span,
        )
        self.containers.append(container)

    def _extract_class_field(self, node: Node, container_id: str) -> VariableNode | None:
        name_n = node.child_by_field_name("name") or node.child_by_field_name("property")
        if not name_n:
            return None
        var_name = node_text(name_n, self.source_bytes)
        type_n = node.child_by_field_name("type")
        val_n = node.child_by_field_name("value")

        declared_type = node_text(type_n, self.source_bytes).lstrip(": ") if type_n else None
        default_val = node_text(val_n, self.source_bytes) if val_n else None
        span = to_source_span(node, self.source_bytes)
        var_id = make_variable_id(self.module_id, var_name, span.start_line)

        var_node = VariableNode(
            id=var_id,
            name=var_name,
            scope="field",
            mutability="mutable",
            declared_type=declared_type,
            inferred_shape=declared_type or "Any",
            default_value=default_val,
            is_optional=False,
            owner_id=container_id,
            module_id=self.module_id,
            span=span,
        )
        self.variables.append(var_node)
        return var_node

    def _extract_method(self, node: Node, container_id: str, class_name: str) -> CallableNode:
        span = to_source_span(node, self.source_bytes)
        name_n = node.child_by_field_name("name")
        m_name = node_text(name_n, self.source_bytes) if name_n else "anonymous"
        qualname = f"{class_name}.{m_name}"
        fn_id = make_callable_id(self.module_id, qualname, span.start_line)
        self._callable_by_name[m_name] = fn_id
        self._callable_by_name[qualname] = fn_id

        kind: CallableKind = "constructor" if m_name == "constructor" else "method"

        # Parameters
        parameters: list[ParameterInfo] = []
        params_n = node.child_by_field_name("parameters")
        if params_n:
            for p_child in params_n.children:
                p_info = self._parse_param(p_child, qualname)
                if p_info:
                    parameters.append(p_info)
                    self.variables.append(
                        VariableNode(
                            id=p_info.id,
                            name=p_info.name,
                            scope="parameter",
                            declared_type=p_info.declared_type,
                            inferred_shape=p_info.inferred_shape,
                            default_value=p_info.default_value,
                            is_optional=p_info.is_optional,
                            owner_id=fn_id,
                            module_id=self.module_id,
                            span=p_info.span,
                        )
                    )

        # Return type
        ret_type_n = node.child_by_field_name("return_type")
        ret_type = node_text(ret_type_n, self.source_bytes).lstrip(": ") if ret_type_n else None

        body = node.child_by_field_name("body")
        source_excerpt = node_text(node, self.source_bytes)

        callable_node = CallableNode(
            id=fn_id,
            name=m_name,
            qualname=qualname,
            kind=kind,
            parameters=parameters,
            return_type=ret_type,
            inferred_return_shape=ret_type or "Any",
            purity="unknown",
            is_async="async" in source_excerpt[:20],
            container_id=container_id,
            module_id=self.module_id,
            span=span,
            source_excerpt=source_excerpt,
        )
        self.callables.append(callable_node)
        if body:
            self._analyze_body(body, fn_id, parameters)
        return callable_node

    def _extract_function(self, node: Node, container_id: str | None, prefix: str = "") -> CallableNode:
        span = to_source_span(node, self.source_bytes)
        name_n = node.child_by_field_name("name")
        fn_name = node_text(name_n, self.source_bytes) if name_n else "anonymous"
        qualname = f"{prefix}{fn_name}"
        fn_id = make_callable_id(self.module_id, qualname, span.start_line)
        self._callable_by_name[fn_name] = fn_id
        self._callable_by_name[qualname] = fn_id

        parameters: list[ParameterInfo] = []
        params_n = node.child_by_field_name("parameters")
        if params_n:
            for p_child in params_n.children:
                p_info = self._parse_param(p_child, fn_name)
                if p_info:
                    parameters.append(p_info)
                    self.variables.append(
                        VariableNode(
                            id=p_info.id,
                            name=p_info.name,
                            scope="parameter",
                            declared_type=p_info.declared_type,
                            inferred_shape=p_info.inferred_shape,
                            default_value=p_info.default_value,
                            is_optional=p_info.is_optional,
                            owner_id=fn_id,
                            module_id=self.module_id,
                            span=p_info.span,
                        )
                    )

        ret_type_n = node.child_by_field_name("return_type")
        ret_type = node_text(ret_type_n, self.source_bytes).lstrip(": ") if ret_type_n else None

        source_excerpt = node_text(node, self.source_bytes)
        body = node.child_by_field_name("body")

        callable_node = CallableNode(
            id=fn_id,
            name=fn_name,
            qualname=qualname,
            kind="function",
            parameters=parameters,
            return_type=ret_type,
            inferred_return_shape=ret_type or "Any",
            purity="pure" if "console.log" not in source_excerpt and "fetch(" not in source_excerpt else "impure",
            is_async="async" in source_excerpt[:20],
            container_id=container_id,
            module_id=self.module_id,
            span=span,
            source_excerpt=source_excerpt,
        )
        self.callables.append(callable_node)
        if body:
            self._analyze_body(body, fn_id, parameters)
        return callable_node

    def _extract_var_declaration(self, node: Node, scope: VariableScope, owner_id: str | None) -> None:
        # e.g. const x = 10, add = (a, b) => a + b;
        is_const = node_text(node.children[0], self.source_bytes) == "const" if node.children else False
        for child in node.children:
            if child.type == "variable_declarator":
                name_n = child.child_by_field_name("name")
                type_n = child.child_by_field_name("type")
                val_n = child.child_by_field_name("value")

                if not name_n:
                    continue

                var_name = node_text(name_n, self.source_bytes)
                # Check if value is arrow function or function expression
                if val_n and val_n.type in ("arrow_function", "function_expression"):
                    # Treat as callable
                    span = to_source_span(child, self.source_bytes)
                    fn_id = make_callable_id(self.module_id, var_name, span.start_line)
                    self._callable_by_name[var_name] = fn_id

                    params: list[ParameterInfo] = []
                    params_n = val_n.child_by_field_name("parameters")
                    if params_n:
                        for p in params_n.children:
                            p_info = self._parse_param(p, var_name)
                            if p_info:
                                params.append(p_info)
                    else:
                        single = val_n.child_by_field_name("parameter")
                        if single:
                            p_info = self._parse_param(single, var_name)
                            if p_info:
                                params.append(p_info)
                    for param in params:
                        self.variables.append(VariableNode(
                            **param.model_dump(), scope="parameter", owner_id=fn_id,
                            module_id=self.module_id,
                        ))

                    ret_t = val_n.child_by_field_name("return_type")
                    ret_str = node_text(ret_t, self.source_bytes).lstrip(": ") if ret_t else None

                    body_n = val_n.child_by_field_name("body")
                    c_node = CallableNode(
                        id=fn_id,
                        name=var_name,
                        qualname=var_name,
                        kind="closure",
                        parameters=params,
                        return_type=ret_str,
                        inferred_return_shape=ret_str or "Any",
                        purity="unknown",
                        is_async="async" in node_text(val_n, self.source_bytes)[:20],
                        module_id=self.module_id,
                        span=span,
                        source_excerpt=("const " if is_const else "let ") + node_text(child, self.source_bytes) + ";",
                    )
                    self.callables.append(c_node)
                    if body_n:
                        self._analyze_body(body_n, fn_id, params)
                else:
                    # Regular variable
                    span = to_source_span(child, self.source_bytes)
                    var_id = make_variable_id(self.module_id, var_name, span.start_line)
                    dec_type = node_text(type_n, self.source_bytes).lstrip(": ") if type_n else None
                    val_str = node_text(val_n, self.source_bytes) if val_n else None

                    v_node = VariableNode(
                        id=var_id,
                        name=var_name,
                        scope=scope,
                        mutability="immutable" if is_const else "mutable",
                        declared_type=dec_type,
                        inferred_shape=dec_type or "Any",
                        default_value=val_str,
                        is_optional=False,
                        owner_id=owner_id,
                        module_id=self.module_id,
                        span=span,
                    )
                    self.variables.append(v_node)

    def _parse_param(self, node: Node, fn_name: str) -> ParameterInfo | None:
        span = to_source_span(node, self.source_bytes)
        name: str | None = None
        declared_type: str | None = None
        default_val: str | None = None
        is_optional: bool = False

        if node.type == "identifier":
            name = node_text(node, self.source_bytes)
        elif node.type == "required_parameter":
            # pattern + type
            p = node.child_by_field_name("pattern")
            t = node.child_by_field_name("type")
            name = node_text(p, self.source_bytes) if p else None
            declared_type = node_text(t, self.source_bytes).lstrip(": ") if t else None
            value = node.child_by_field_name("value")
            if value:
                default_val = node_text(value, self.source_bytes)
                is_optional = True
        elif node.type == "optional_parameter":
            p = node.child_by_field_name("pattern")
            t = node.child_by_field_name("type")
            name = node_text(p, self.source_bytes) if p else None
            declared_type = node_text(t, self.source_bytes).lstrip(": ") if t else None
            is_optional = True
        elif node.type == "assignment_pattern":
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            name = node_text(left, self.source_bytes) if left else None
            default_val = node_text(right, self.source_bytes) if right else None
            is_optional = True

        if not name or name in (",", "(", ")"):
            return None

        return ParameterInfo(
            id=make_param_id(self.module_id, fn_name, name),
            name=name,
            declared_type=declared_type,
            inferred_shape=declared_type or "Any",
            default_value=default_val,
            is_optional=is_optional,
            span=span,
        )

    def _analyze_body(self, body_node: Node, fn_id: str, parameters: list[ParameterInfo]) -> None:
        seq_order = 0
        df_step = 0

        # Input data flow
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

        # Find calls
        calls = sorted(self._find_nodes_of_type(body_node, "call_expression")
                       + self._find_nodes_of_type(body_node, "new_expression"), key=lambda node: node.start_byte)
        for c in calls:
            seq_order += 1
            self._call_counter += 1
            func_n = c.child_by_field_name("function") or c.child_by_field_name("constructor")
            args_n = c.child_by_field_name("arguments")
            tname = node_text(func_n, self.source_bytes) if func_n else "anonymous"

            arg_texts: list[str] = []
            if args_n:
                for arg in args_n.children:
                    if arg.type not in ("(", ")", ","):
                        arg_texts.append(node_text(arg, self.source_bytes))

            self.calls.append(
                CallEdge(
                    id=f"edge:call:{self._call_counter}",
                    source_id=fn_id,
                    target_id=tname,
                    target_name=tname,
                    sequence_order=seq_order,
                    arguments=arg_texts,
                    span=to_source_span(c, self.source_bytes),
                )
            )

        # Find return statements
        returns = self._find_nodes_of_type(body_node, "return_statement")
        for ret in returns:
            df_step += 1
            self._df_counter += 1
            ret_text = node_text(ret, self.source_bytes)
            self.data_flows.append(
                DataFlowEdge(
                    id=f"edge:df:{self._df_counter}",
                    source_id=fn_id,
                    target_id=fn_id,
                    variable_name="<return>",
                    step=df_step,
                    transformation_summary=f"Returns: {ret_text[:40]}",
                    span=to_source_span(ret, self.source_bytes),
                )
            )

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
            if tname in self._callable_by_name:
                call.target_id = self._callable_by_name[tname]
            elif tname in containers_by_name:
                call.target_id = containers_by_name[tname]
            elif tname in self._dep_by_symbol:
                call.target_id = self._dep_by_symbol[tname]
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

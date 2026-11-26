"""High-level builder that compiles arbitrary source code into ProgramIR."""
from __future__ import annotations

import uuid
from app.models.ir import Diagnostic, IRMetadata, ProgramIR, SourceSpan
from app.parser.base import to_source_span
from app.parser.graph_slicer import GraphSlicer
from app.parser.js_ts_extractor import JsTsExtractor
from app.parser.languages import detect_language, get_parser, get_runtime_paradigm
from app.parser.python_extractor import PythonExtractor


def build_program_ir(
    source_code: str,
    file_path: str = "snippet",
    language: str | None = None,
    analysis_id: str | None = None,
) -> ProgramIR:
    """Deterministically parse source code via Tree-sitter and construct ProgramIR."""
    # 1. Normalize line endings
    normalized_code = source_code.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized_code.endswith("\n"):
        normalized_code += "\n"

    # 2. Detect language
    detected_lang = (language or detect_language(normalized_code, filename=file_path)).lower()
    if detected_lang not in {"python", "javascript", "typescript"}:
        raise ValueError(f"Structural extraction for '{detected_lang}' is not implemented. Use Python, JavaScript, or TypeScript.")
    runtime_paradigm = get_runtime_paradigm(detected_lang)
    aid = analysis_id or f"analysis_{uuid.uuid4().hex[:12]}"

    diagnostics: list[Diagnostic] = []

    # 3. Parse with Tree-sitter
    try:
        parser, ts_lang = get_parser(detected_lang)
        tree = parser.parse(normalized_code.encode("utf-8"))
    except Exception as e:
        diagnostics.append(
            Diagnostic(
                severity="error",
                message=f"Tree-sitter parser failed: {e}",
                span=SourceSpan(start_line=1, end_line=1, start_col=0, end_col=0),
            )
        )
        metadata = IRMetadata(
            primary_language=detected_lang,
            runtime_paradigm=runtime_paradigm,
            diagnostics=diagnostics,
        )
        return ProgramIR(analysis_id=aid, metadata=metadata)

    # 4. Extract symbols, dependencies, and edges
    if detected_lang in ("javascript", "typescript"):
        extractor = JsTsExtractor(normalized_code, file_path=file_path, language=detected_lang)
        modules, dependencies, symbols, edges = extractor.extract(tree)
    else:
        # Default to Python extractor
        extractor = PythonExtractor(normalized_code, file_path=file_path)
        modules, dependencies, symbols, edges = extractor.extract(tree)

    # Diagnostic for syntax errors in Tree-sitter tree if root has errors
    if tree.root_node.has_error:
        diagnostics.append(
            Diagnostic(
                severity="warning",
                message="Source code contains syntax errors or unparsed tokens.",
                span=to_source_span(tree.root_node),
            )
        )

    # 5. Build preliminary IR for graph analysis
    # Resolve local inheritance to actual IDs rather than synthetic line-zero IDs.
    containers_by_name = {c.name: c.id for c in symbols.containers}
    for relation in edges.type_relations:
        if relation.target_name in containers_by_name:
            relation.target_id = containers_by_name[relation.target_name]

    metadata = IRMetadata(
        primary_language=detected_lang,
        runtime_paradigm=runtime_paradigm,
        entry_points=[],
        topological_order=[],
        diagnostics=diagnostics,
    )

    temp_ir = ProgramIR(
        analysis_id=aid,
        metadata=metadata,
        modules=modules,
        dependencies=dependencies,
        symbols=symbols,
        edges=edges,
    )

    # 6. Run GraphSlicer to compute entry points and topological order
    slicer = GraphSlicer(temp_ir)
    metadata.entry_points = slicer.compute_entry_points()
    metadata.topological_order = slicer.compute_topological_order()

    return ProgramIR(
        analysis_id=aid,
        metadata=metadata,
        modules=modules,
        dependencies=dependencies,
        symbols=symbols,
        edges=edges,
    )

"""Unit tests for Pydantic IR models."""
import pytest
from pydantic import ValidationError

from app.models.ir import (
    CallEdge,
    CallableNode,
    ContainerNode,
    DataFlowEdge,
    DependencyNode,
    Diagnostic,
    EdgesCollection,
    IRMetadata,
    IRSlice,
    ModuleNode,
    ParameterInfo,
    ProgramIR,
    SourceSpan,
    SymbolsCollection,
    TypeRelationEdge,
    VariableNode,
)


def test_source_span_valid():
    span = SourceSpan(start_line=1, end_line=5, start_col=0, end_col=10)
    assert span.start_line == 1
    assert span.end_line == 5
    assert span.start_col == 0
    assert span.end_col == 10

    # Same line valid
    span_same_line = SourceSpan(start_line=2, end_line=2, start_col=4, end_col=8)
    assert span_same_line.start_col <= span_same_line.end_col


def test_source_span_invalid():
    # end_line < start_line
    with pytest.raises(ValidationError):
        SourceSpan(start_line=5, end_line=2, start_col=0, end_col=10)

    # same line, end_col < start_col
    with pytest.raises(ValidationError):
        SourceSpan(start_line=2, end_line=2, start_col=10, end_col=5)

    # line < 1
    with pytest.raises(ValidationError):
        SourceSpan(start_line=0, end_line=1, start_col=0, end_col=5)


def test_program_ir_serialization_roundtrip():
    span = SourceSpan(start_line=1, end_line=10, start_col=0, end_col=0)

    meta = IRMetadata(
        primary_language="python",
        runtime_paradigm="imperative/functional",
        entry_points=["sym:func:mod_1:main:1"],
        topological_order=["sym:func:mod_1:helper:5", "sym:func:mod_1:main:1"],
        diagnostics=[
            Diagnostic(severity="info", message="Parsed successfully", span=span)
        ],
    )

    module = ModuleNode(
        id="mod:mod_1",
        path="main.py",
        language="python",
        line_count=10,
        span=span,
    )

    dep = DependencyNode(
        id="dep:math",
        name="math",
        alias="m",
        imported_symbols=["sqrt"],
        category="stdlib",
        module_id="mod:mod_1",
        span=span,
    )

    var = VariableNode(
        id="sym:var:mod_1:x:3",
        name="x",
        scope="local",
        mutability="mutable",
        declared_type="int",
        inferred_shape="int",
        default_value="42",
        is_optional=False,
        owner_id="sym:func:mod_1:main:1",
        module_id="mod:mod_1",
        span=SourceSpan(start_line=3, end_line=3, start_col=4, end_col=10),
    )

    param = ParameterInfo(
        id="param:mod_1:main:arg1",
        name="arg1",
        declared_type="int",
        inferred_shape="int",
        default_value="0",
        is_optional=True,
        span=SourceSpan(start_line=1, end_line=1, start_col=9, end_col=18),
    )

    func = CallableNode(
        id="sym:func:mod_1:main:1",
        name="main",
        qualname="main",
        kind="function",
        parameters=[param],
        return_type="int",
        inferred_return_shape="int",
        purity="pure",
        is_async=False,
        module_id="mod:mod_1",
        span=SourceSpan(start_line=1, end_line=4, start_col=0, end_col=12),
        source_excerpt="def main(arg1: int = 0) -> int:\n    x = 42\n    return x + arg1\n",
    )

    container = ContainerNode(
        id="sym:container:mod_1:MyClass:6",
        name="MyClass",
        kind="class",
        bases=["object"],
        field_ids=[],
        method_ids=[],
        module_id="mod:mod_1",
        span=SourceSpan(start_line=6, end_line=9, start_col=0, end_col=12),
    )

    call_edge = CallEdge(
        id="edge:call:1",
        source_id="sym:func:mod_1:main:1",
        target_id="sym:func:mod_1:helper:5",
        target_name="helper",
        sequence_order=1,
        arguments=["x"],
        span=SourceSpan(start_line=3, end_line=3, start_col=4, end_col=14),
    )

    df_edge = DataFlowEdge(
        id="edge:df:1",
        source_id="param:mod_1:main:arg1",
        target_id="sym:var:mod_1:x:3",
        variable_name="x",
        step=1,
        transformation_summary="Assigned local variable x with offset",
        span=SourceSpan(start_line=3, end_line=3, start_col=4, end_col=10),
    )

    tr_edge = TypeRelationEdge(
        id="edge:tr:1",
        source_id="sym:container:mod_1:MyClass:6",
        target_id="sym:container:object",
        target_name="object",
        relation="inherits",
        span=SourceSpan(start_line=6, end_line=6, start_col=0, end_col=20),
    )

    ir = ProgramIR(
        analysis_id="analysis_123",
        metadata=meta,
        modules=[module],
        dependencies=[dep],
        symbols=SymbolsCollection(
            containers=[container],
            callables=[func],
            variables=[var],
        ),
        edges=EdgesCollection(
            calls=[call_edge],
            data_flows=[df_edge],
            type_relations=[tr_edge],
        ),
    )

    # Serialize to JSON and parse back
    json_data = ir.model_dump_json()
    reloaded = ProgramIR.model_validate_json(json_data)

    assert reloaded.analysis_id == "analysis_123"
    assert reloaded.metadata.primary_language == "python"
    assert len(reloaded.modules) == 1
    assert len(reloaded.dependencies) == 1
    assert len(reloaded.symbols.callables) == 1
    assert reloaded.symbols.callables[0].name == "main"
    assert len(reloaded.edges.calls) == 1
    assert reloaded.edges.calls[0].sequence_order == 1


def test_ir_slice_serialization():
    span = SourceSpan(start_line=1, end_line=5, start_col=0, end_col=0)
    func = CallableNode(
        id="sym:func:target:1",
        name="target_func",
        qualname="target_func",
        module_id="mod:1",
        span=span,
        source_excerpt="def target_func(): pass",
    )

    slice_obj = IRSlice(
        analysis_id="analysis_abc",
        target_symbol_id="sym:func:target:1",
        primary_language="python",
        runtime_paradigm="imperative",
        target_callable=func,
    )

    json_str = slice_obj.model_dump_json()
    reloaded = IRSlice.model_validate_json(json_str)
    assert reloaded.target_symbol_id == "sym:func:target:1"
    assert reloaded.target_callable.name == "target_func"

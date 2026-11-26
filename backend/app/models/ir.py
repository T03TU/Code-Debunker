"""Normalized flat property-graph JSON Intermediate Representation (IR) models."""

from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field, model_validator


class SourceSpan(BaseModel):
    """Exact source code coordinates for click-to-highlight synchronization."""

    start_line: int = Field(..., ge=1, description="1-based inclusive start line")
    end_line: int = Field(..., ge=1, description="1-based inclusive end line")
    start_col: int = Field(..., ge=0, description="0-based start column")
    end_col: int = Field(..., ge=0, description="0-based end column")

    @model_validator(mode="after")
    def validate_line_order(self) -> "SourceSpan":
        if self.end_line < self.start_line:
            raise ValueError(
                f"end_line ({self.end_line}) must be >= start_line ({self.start_line})"
            )
        if self.end_line == self.start_line and self.end_col < self.start_col:
            raise ValueError(
                f"end_col ({self.end_col}) must be >= start_col ({self.start_col}) on same line"
            )
        return self


class Diagnostic(BaseModel):
    """Parser or analysis diagnostic attached to the IR."""

    severity: Literal["info", "warning", "error"]
    message: str
    span: SourceSpan | None = None


class IRMetadata(BaseModel):
    """Top-level IR metadata and graph execution summary."""

    primary_language: str
    runtime_paradigm: str = "unknown"
    entry_points: list[str] = Field(default_factory=list)
    topological_order: list[str] = Field(default_factory=list)
    diagnostics: list[Diagnostic] = Field(default_factory=list)


class ModuleNode(BaseModel):
    """Source module metadata."""

    id: str
    path: str
    language: str
    line_count: int = Field(..., ge=0)
    span: SourceSpan


DependencyCategory = Literal["stdlib", "third_party", "internal_module", "unresolved"]


class DependencyNode(BaseModel):
    """Categorized import/module dependency."""

    id: str
    name: str
    alias: str | None = None
    imported_symbols: list[str] = Field(default_factory=list)
    category: DependencyCategory
    module_id: str
    span: SourceSpan


VariableScope = Literal["global", "field", "parameter", "local"]
Mutability = Literal["mutable", "immutable", "unknown"]


class VariableNode(BaseModel):
    """Variable, parameter, or class field symbol."""

    id: str
    name: str
    scope: VariableScope
    mutability: Mutability = "mutable"
    declared_type: str | None = None
    inferred_shape: str | None = None
    default_value: str | None = None
    is_optional: bool = False
    owner_id: str | None = None
    module_id: str
    span: SourceSpan


class ParameterInfo(BaseModel):
    """Structured parameter metadata embedded on a callable."""

    id: str
    name: str
    declared_type: str | None = None
    inferred_shape: str | None = None
    default_value: str | None = None
    is_optional: bool = False
    span: SourceSpan


CallableKind = Literal["function", "method", "closure", "constructor"]
Purity = Literal["pure", "impure", "unknown"]


class CallableNode(BaseModel):
    """Function, method, constructor, or closure symbol."""

    id: str
    name: str
    qualname: str
    kind: CallableKind = "function"
    parameters: list[ParameterInfo] = Field(default_factory=list)
    return_type: str | None = None
    inferred_return_shape: str | None = None
    purity: Purity = "unknown"
    is_async: bool = False
    container_id: str | None = None
    module_id: str
    span: SourceSpan
    source_excerpt: str = ""


ContainerKind = Literal["class", "struct", "interface", "enum"]


class ContainerNode(BaseModel):
    """Class, struct, interface, or enum container symbol."""

    id: str
    name: str
    kind: ContainerKind = "class"
    bases: list[str] = Field(default_factory=list)
    field_ids: list[str] = Field(default_factory=list)
    method_ids: list[str] = Field(default_factory=list)
    module_id: str
    span: SourceSpan


class SymbolsCollection(BaseModel):
    """All symbols extracted from the analyzed code."""

    containers: list[ContainerNode] = Field(default_factory=list)
    callables: list[CallableNode] = Field(default_factory=list)
    variables: list[VariableNode] = Field(default_factory=list)


class CallEdge(BaseModel):
    """Control-flow invocation edge between callables or external dependencies."""

    id: str
    source_id: str
    target_id: str
    target_name: str
    sequence_order: int = Field(..., ge=1)
    arguments: list[str] = Field(default_factory=list)
    span: SourceSpan


class DataFlowEdge(BaseModel):
    """Def-use value transformation edge within or across symbols."""

    id: str
    source_id: str
    target_id: str
    variable_name: str
    step: int = Field(..., ge=1)
    transformation_summary: str
    span: SourceSpan


TypeRelationKind = Literal["inherits", "implements", "composes"]


class TypeRelationEdge(BaseModel):
    """Structural type relationship edge."""

    id: str
    source_id: str
    target_id: str
    target_name: str
    relation: TypeRelationKind
    span: SourceSpan


class EdgesCollection(BaseModel):
    """All control-flow, data-flow, and type edges."""

    calls: list[CallEdge] = Field(default_factory=list)
    data_flows: list[DataFlowEdge] = Field(default_factory=list)
    type_relations: list[TypeRelationEdge] = Field(default_factory=list)


class ProgramIR(BaseModel):
    """Complete normalized flat property-graph Intermediate Representation."""

    analysis_id: str
    metadata: IRMetadata
    modules: list[ModuleNode] = Field(default_factory=list)
    dependencies: list[DependencyNode] = Field(default_factory=list)
    symbols: SymbolsCollection = Field(default_factory=SymbolsCollection)
    edges: EdgesCollection = Field(default_factory=EdgesCollection)


class IRSlice(BaseModel):
    """1-hop NetworkX context slice centered on a target callable symbol."""

    analysis_id: str
    target_symbol_id: str
    primary_language: str
    runtime_paradigm: str
    target_callable: CallableNode
    upstream_callables: list[CallableNode] = Field(default_factory=list)
    downstream_callables: list[CallableNode] = Field(default_factory=list)
    related_containers: list[ContainerNode] = Field(default_factory=list)
    dependencies: list[DependencyNode] = Field(default_factory=list)
    variables: list[VariableNode] = Field(default_factory=list)
    calls: list[CallEdge] = Field(default_factory=list)
    data_flows: list[DataFlowEdge] = Field(default_factory=list)
    type_relations: list[TypeRelationEdge] = Field(default_factory=list)

"""UML graph models for Feature B — React Flow + ELKjs diagram payloads."""
from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field

from app.models.ir import SourceSpan


class UMLNodeData(BaseModel):
    label: str
    kind: Literal["callable", "container", "variable", "dependency", "external"]
    span: SourceSpan | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class UMLNode(BaseModel):
    id: str
    type: Literal["umlNode"] = "umlNode"
    position: dict[str, float] = Field(default_factory=lambda: {"x": 0.0, "y": 0.0})
    data: UMLNodeData
    source_id: str  # links back to IR symbol id


class UMLEdgeData(BaseModel):
    label: str
    kind: Literal["call", "data_flow", "type_relation", "dependency"]
    span: SourceSpan | None = None
    sequence_order: int | None = None
    step: int | None = None


class UMLEdge(BaseModel):
    id: str
    source: str  # UMLNode id
    target: str  # UMLNode id
    data: UMLEdgeData
    animated: bool = False
    source_edge_id: str  # links back to IR edge id


class UMLDiagram(BaseModel):
    view: Literal["class", "dataflow"]
    nodes: list[UMLNode]
    edges: list[UMLEdge]
    elk_options: dict[str, Any] = Field(
        default_factory=lambda: {
            "elk.algorithm": "layered",
            "elk.direction": "DOWN",
            "elk.layered.spacing.nodeNodeBetweenLayers": "80",
            "elk.spacing.nodeNode": "40",
        }
    )

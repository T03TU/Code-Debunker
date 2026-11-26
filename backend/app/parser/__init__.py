"""Parser package for AST parsing and IR generation."""
from app.parser.ir_builder import build_program_ir
from app.parser.graph_slicer import GraphSlicer
from app.parser.languages import detect_language

__all__ = ["build_program_ir", "GraphSlicer", "detect_language"]

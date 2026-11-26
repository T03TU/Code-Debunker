"""Unit tests for Tree-sitter deterministic AST parsing and 1-hop IR slicing."""
import pytest
from app.parser.ir_builder import build_program_ir
from app.parser.graph_slicer import GraphSlicer
from app.parser.languages import detect_language


PYTHON_SAMPLE = '''
import math
from typing import List, Optional
import requests

PI_CONSTANT = 3.14159

class Shape:
    def __init__(self, name: str) -> None:
        self.name = name

    def get_area(self) -> float:
        return 0.0

class Circle(Shape):
    def __init__(self, radius: float) -> None:
        super().__init__("circle")
        self.radius = radius

    def get_area(self) -> float:
        r = self.radius
        area = math.pi * (r ** 2)
        return area

def compute_total_area(circles: List[Circle]) -> float:
    total = 0.0
    for c in circles:
        total += c.get_area()
    return total

def main() -> None:
    c1 = Circle(5.0)
    c2 = Circle(10.0)
    result = compute_total_area([c1, c2])
    return result
'''

TS_SAMPLE = '''
import { format } from 'date-fns';
import * as path from 'path';

interface Animal {
    name: string;
}

class Dog implements Animal {
    public name: string;
    constructor(name: string) {
        this.name = name;
    }
    public bark(): string {
        return `Woof from ${this.name}`;
    }
}

export function playWithDog(dogName: string): string {
    const dog = new Dog(dogName);
    const sound = dog.bark();
    return sound;
}
'''


def test_language_detection():
    assert detect_language("def foo(): pass", "sample.py") == "python"
    assert detect_language("function foo() {}", "sample.js") == "javascript"
    assert detect_language("interface User { id: number; }", "sample.ts") == "typescript"
    assert detect_language("package main\nfunc main() {}", "main.go") == "go"
    assert detect_language("public class Main {}", "Main.java") == "java"


def test_python_ast_extraction():
    ir = build_program_ir(source_code=PYTHON_SAMPLE, file_path="shapes.py")

    assert ir.metadata.primary_language == "python"
    assert len(ir.modules) == 1
    assert ir.modules[0].path == "shapes.py"

    # Verify dependencies
    dep_names = {d.name for d in ir.dependencies}
    assert "math" in dep_names
    assert "requests" in dep_names
    # Category checks
    math_dep = next(d for d in ir.dependencies if d.name == "math")
    assert math_dep.category == "stdlib"
    requests_dep = next(d for d in ir.dependencies if d.name == "requests")
    assert requests_dep.category == "third_party"

    # Verify containers
    container_names = {c.name for c in ir.symbols.containers}
    assert "Shape" in container_names
    assert "Circle" in container_names

    circle_container = next(c for c in ir.symbols.containers if c.name == "Circle")
    assert "Shape" in circle_container.bases

    # Verify inheritance edge
    assert any(
        tr.relation == "inherits" and tr.target_name == "Shape"
        for tr in ir.edges.type_relations
    )

    # Verify callables
    callable_names = {c.name for c in ir.symbols.callables}
    assert "__init__" in callable_names
    assert "get_area" in callable_names
    assert "compute_total_area" in callable_names
    assert "main" in callable_names

    # Verify parameters of compute_total_area
    compute_fn = next(c for c in ir.symbols.callables if c.name == "compute_total_area")
    assert len(compute_fn.parameters) == 1
    assert compute_fn.parameters[0].name == "circles"
    assert "Circle" in str(compute_fn.parameters[0].declared_type)
    assert compute_fn.return_type == "float"

    # Verify exact SourceSpan integrity (all non-null, 1-based, start <= end)
    for c in ir.symbols.callables:
        assert c.span.start_line >= 1
        assert c.span.end_line >= c.span.start_line
        assert c.span.start_col >= 0
        assert c.span.end_col >= 0

    # Verify entry points
    assert len(ir.metadata.entry_points) > 0
    # main should be among entry points
    main_callable = next(c for c in ir.symbols.callables if c.name == "main")
    assert main_callable.id in ir.metadata.entry_points


def test_ts_ast_extraction():
    ir = build_program_ir(source_code=TS_SAMPLE, file_path="animals.ts", language="typescript")

    assert ir.metadata.primary_language == "typescript"
    # Dependencies
    dep_names = {d.name for d in ir.dependencies}
    assert "path" in dep_names or "date-fns" in dep_names

    # Container / interface
    container_names = {c.name for c in ir.symbols.containers}
    assert "Animal" in container_names or "Dog" in container_names

    # Callables
    callable_names = {c.name for c in ir.symbols.callables}
    assert "playWithDog" in callable_names


def test_1hop_slicing():
    ir = build_program_ir(source_code=PYTHON_SAMPLE, file_path="shapes.py")
    slicer = GraphSlicer(ir)

    # Slice around compute_total_area
    compute_fn = next(c for c in ir.symbols.callables if c.name == "compute_total_area")
    ir_slice = slicer.extract_1hop_slice(target_symbol_id=compute_fn.id)

    assert ir_slice.target_symbol_id == compute_fn.id
    assert ir_slice.target_callable.name == "compute_total_area"

    # Upstream caller of compute_total_area is main
    upstream_names = {c.name for c in ir_slice.upstream_callables}
    assert "main" in upstream_names

    # Downstream callee of compute_total_area is get_area
    downstream_names = {c.name for c in ir_slice.downstream_callables}
    assert "get_area" in downstream_names

    # Target parameters and variables must be preserved
    assert len(ir_slice.target_callable.parameters) == 1
    assert ir_slice.target_callable.parameters[0].name == "circles"

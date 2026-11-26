import pytest

from app.debunk.uml_builder import build_class_diagram, build_dataflow_diagram
from app.parser.graph_slicer import GraphSlicer
from app.parser.ir_builder import build_program_ir


def test_slice_does_not_leak_neighbor_calls_into_second_hop():
    code = '''def far_away():
    return 0

def helper():
    return far_away()

def target():
    return helper()

def upstream():
    return target() + far_away()
'''
    ir = build_program_ir(code)
    sliced = GraphSlicer(ir).extract_1hop_slice('target')
    assert {item.name for item in sliced.downstream_callables} == {'helper'}
    assert {item.name for item in sliced.upstream_callables} == {'upstream'}
    assert all(edge.target_name != 'far_away' for edge in sliced.calls)
    with pytest.raises(ValueError, match='not found'):
        GraphSlicer(ir).extract_1hop_slice('missing')


def test_inheritance_points_to_real_container_id():
    ir = build_program_ir('class Base:\n    pass\n\nclass Child(Base):\n    pass\n')
    base = next(item for item in ir.symbols.containers if item.name == 'Base')
    assert ir.edges.type_relations[0].target_id == base.id


@pytest.mark.parametrize('code,language', [
    ('def total(items):\n    result = sum(items)\n    return result\n', 'python'),
    ('export const double = value => value * 2;', 'javascript'),
    ('export function double(value: number = 2) { return Math.abs(value * 2); }', 'typescript'),
])
def test_diagram_nodes_are_unique_and_every_edge_has_endpoints(code, language):
    ir = build_program_ir(code, language=language)
    sliced = GraphSlicer(ir).extract_1hop_slice()
    for diagram in [build_class_diagram(ir), build_dataflow_diagram(sliced)]:
        ids = {node.id for node in diagram.nodes}
        assert len(ids) == len(diagram.nodes)
        assert all(edge.source in ids and edge.target in ids for edge in diagram.edges)
        assert all(node.data.span for node in diagram.nodes)
        assert all(edge.data.span for edge in diagram.edges)


def test_decorated_python_functions_and_methods_are_extracted():
    ir = build_program_ir('@decorator\ndef target():\n    return 1\n\nclass Service:\n    @staticmethod\n    def run(value):\n        return value\n')
    assert {item.qualname for item in ir.symbols.callables} == {'target', 'Service.run'}


@pytest.mark.parametrize('language,code', [
    ('python', 'class First:\n    def run(self, value):\n        return value\n\nclass Second:\n    def run(self, value):\n        return value\n'),
    ('typescript', 'class First { run(value: number) { return value; } }\nclass Second { run(value: number) { return value; } }'),
])
def test_method_parameters_are_scoped_to_qualified_callable(language, code):
    ir = build_program_ir(code, language=language)
    ids = [param.id for fn in ir.symbols.callables for param in fn.parameters]
    assert len(ids) == len(set(ids)) == 2


def test_typescript_parameter_default_preserved():
    ir = build_program_ir('function scale(value: number, factor: number = 2) { return value * factor; }', language='typescript')
    param = ir.symbols.callables[0].parameters[1]
    assert param.default_value == '2'
    assert param.is_optional


def test_unicode_columns_use_monaco_utf16_coordinates():
    ir = build_program_ir('const café = (value) => value; const plain = (value) => value;', language='javascript')
    plain = next(item for item in ir.symbols.callables if item.name == 'plain')
    assert plain.span.start_col == 37


@pytest.mark.parametrize('language,code', [
    ('python', 'class Product:\n    pass\n\ndef main():\n    return Product()\n'),
    ('javascript', 'class Product {}\nfunction main() { return new Product(); }'),
])
def test_constructor_calls_resolve_to_container(language, code):
    ir = build_program_ir(code, language=language)
    product = next(item for item in ir.symbols.containers if item.name == 'Product')
    edge = next(edge for edge in ir.edges.calls if edge.target_name == 'Product')
    assert edge.target_id == product.id

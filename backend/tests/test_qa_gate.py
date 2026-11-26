import pytest

from app.models.llm import GeneratedTestSuite
from app.parser.graph_slicer import GraphSlicer
from app.parser.ir_builder import build_program_ir
from app.sandbox.qa_gate import QAGater

SOURCE = 'def double(value: int = 2) -> int:\n    return value * 2\n'
ANNOTATED = '''def double(value: int = 2) -> int:
    """Double the input.

    Args:
        value (int, optional): A number. Defaults to 2.
    Returns:
        int: The doubled value.
    """
    # Apply the multiplication.
    return value * 2
'''


@pytest.fixture
def ir_slice():
    return GraphSlicer(build_program_ir(SOURCE)).extract_1hop_slice()


def test_annotations_preserve_original_logic(ir_slice):
    assert QAGater.validate_annotation(ir_slice, ANNOTATED) == []
    assert any('executable logic' in error for error in QAGater.validate_annotation(ir_slice, ANNOTATED.replace('* 2', '* 3')))


def test_parameter_signature_cannot_substitute_for_documentation(ir_slice):
    errors = QAGater.validate_annotation(ir_slice, ANNOTATED.replace('value (int, optional): A number. Defaults to 2.', 'A number. Defaults to 2.'))
    assert any("'value'" in error for error in errors)


def test_missing_default_and_return_documentation_rejected(ir_slice):
    errors = QAGater.validate_annotation(ir_slice, ANNOTATED.replace('Defaults to 2.', '').replace('Returns:', 'Result:'))
    assert any('default' in error for error in errors)
    assert any('return value' in error for error in errors)


def test_adjacent_helper_does_not_pass_target_anchoring(ir_slice):
    assert QAGater.validate_annotation(ir_slice, 'def other():\n    """double"""\n    return 0\n')


def test_javascript_annotation_uses_jsdoc_and_preserves_tokens():
    source = 'export function double(value) { return value * 2; }'
    sliced = GraphSlicer(build_program_ir(source, language='javascript')).extract_1hop_slice()
    annotated = '/** Double an amount.\n * @param value The input.\n * @returns Twice the input.\n */\n' + source
    assert QAGater.validate_annotation(sliced, annotated) == []
    assert QAGater.validate_annotation(sliced, annotated.replace('value * 2', 'value * 3'))


def test_tests_must_reference_selected_target_and_fixed_module(ir_slice):
    suite = GeneratedTestSuite(language='python', framework='pytest', test_code='from source_target import double\n\ndef test_it():\n    assert double(2) == 4\n', mock_summary='none', test_case_names=['test_it'])
    assert QAGater.validate_tests(ir_slice, suite) == []
    assert QAGater.validate_tests(ir_slice, suite.model_copy(update={'test_code': 'def test_other():\n    assert True\n'}))
    assert QAGater.validate_tests(ir_slice, suite.model_copy(update={'framework': 'jest'}))

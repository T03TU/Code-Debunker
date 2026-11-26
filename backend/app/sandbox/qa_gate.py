"""Validate generated artifacts against their Tree-sitter-grounded target."""
from __future__ import annotations

import re
import textwrap

from pydantic import BaseModel, Field

from app.models.ir import IRSlice, ProgramIR
from app.models.llm import GeneratedTestSuite
from app.parser.base import node_text
from app.parser.languages import get_parser


class QAGateResult(BaseModel):
    passed: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _walk(node):
    yield node
    for child in node.children:
        yield from _walk(child)


def _parse_target(code: str, ir_slice: IRSlice):
    code = textwrap.dedent(code).strip()
    if code.startswith('```') and code.endswith('```'):
        code = '\n'.join(code.splitlines()[1:-1])
    parser, _ = get_parser(ir_slice.primary_language)
    encoded = code.encode()
    tree = parser.parse(encoded)
    if tree.root_node.has_error and ir_slice.primary_language != 'python' and ir_slice.target_callable.container_id:
        encoded = ('class Target {\n' + code + '\n}').encode()
        tree = parser.parse(encoded)
    types = {'function_definition', 'function_declaration', 'method_definition', 'variable_declarator'}
    target = next((node for node in _walk(tree.root_node)
                   if node.type in types and node.child_by_field_name('name') is not None
                   and node_text(node.child_by_field_name('name'), encoded) == ir_slice.target_callable.name), None)
    return tree, target, encoded


def _docstring(node):
    body = node.child_by_field_name('body')
    if body and body.named_children:
        first = next((child for child in body.named_children if child.type != 'comment'), None)
        if first and first.type == 'expression_statement' and first.named_children:
            if first.named_children[0].type in {'string', 'concatenated_string'}:
                return first
    return None


def _fingerprint(node, encoded: bytes):
    """Compare executable tokens, excluding comments and each callable's docstring."""
    ignored = (_docstring(node.parent) if node.type == 'block' and node.parent
               and node.parent.type == 'function_definition' else None)
    result = []
    for child in node.children:
        if child.type == 'comment' or child == ignored:
            continue
        if child.children:
            result.extend(_fingerprint(child, encoded))
        else:
            result.append((child.type, node_text(child, encoded)))
    return result


class QAGater:
    @staticmethod
    def validate_annotation(ir_slice: IRSlice, annotated_code: str) -> list[str]:
        errors = []
        tree, target, encoded = _parse_target(annotated_code, ir_slice)
        if tree.root_node.has_error or target is None:
            return ['Annotated code must be valid source defining the selected callable.']
        _, original, original_bytes = _parse_target(ir_slice.target_callable.source_excerpt, ir_slice)
        if original is None or _fingerprint(original, original_bytes) != _fingerprint(target, encoded):
            errors.append('Annotated code changes executable logic; preserve the original target exactly.')

        if ir_slice.primary_language == 'python':
            doc = _docstring(target)
            documentation = node_text(doc, encoded) if doc else ''
        else:
            documentation = '\n'.join(node_text(node, encoded) for node in _walk(tree.root_node)
                                      if node.type == 'comment' and node_text(node, encoded).startswith('/**'))
        if not documentation:
            return errors + ['Provide a comprehensive Google-style docstring or JSDoc block.']
        parameter_docs = ''
        if ir_slice.primary_language == 'python':
            for heading in ('Args:', 'Parameters:'):
                if heading in documentation:
                    parameter_docs = re.split(r'\n\s*(?:Returns|Raises|Yields|Examples|Attributes):',
                                              documentation.split(heading, 1)[1])[0]
                    break
        else:
            parameter_docs = '\n'.join(line for line in documentation.splitlines() if '@param' in line)
        for param in ir_slice.target_callable.parameters:
            # Only documentation counts. A name in the function signature cannot pass.
            if not re.search(r'(?<!\w)' + re.escape(param.name) + r'(?!\w)', parameter_docs):
                errors.append(f"Document parameter '{param.name}' inside the docstring.")
            if param.default_value is not None and param.default_value not in documentation:
                errors.append(f"Document the default {param.default_value!r} for '{param.name}'.")
        if ir_slice.target_callable.parameters and not any(term in documentation for term in ('Args:', 'Parameters:', '@param')):
            errors.append('Document parameters using Args: or @param entries.')
        if ir_slice.target_callable.return_type not in {'None', 'void', 'NoneType'}:
            if not any(term in documentation.lower() for term in ('returns:', '@return')):
                errors.append('Document the return value using Returns: or @returns.')
        return errors

    @staticmethod
    def validate_pedagogical_completeness(language_id: str, feynman_explanation: str,
                                         annotated_code: str, walkthrough: str,
                                         prerequisites: list[str], ir_slice: IRSlice | None = None) -> list[str]:
        errors = []
        for name, value in [('Language Identification', language_id), ('Feynman Explanation', feynman_explanation),
                            ('Annotated Code', annotated_code), ('Simulated Execution Walkthrough', walkthrough)]:
            if not value.strip():
                errors.append(f'Missing section: {name}.')
        if not 3 <= len(prerequisites) <= 5:
            errors.append('Provide 3–5 prerequisite concepts.')
        if ir_slice:
            errors.extend(QAGater.validate_annotation(ir_slice, annotated_code))
        return errors

    @staticmethod
    def validate_tests(ir_slice: IRSlice, tests: GeneratedTestSuite) -> list[str]:
        errors = QAGater.validate_flow_tests(ir_slice.primary_language, tests)
        parser, _ = get_parser(ir_slice.primary_language)
        code = tests.test_code.encode()
        tree = parser.parse(code)
        identifiers = {node_text(node, code) for node in _walk(tree.root_node)
                       if node.type in {'identifier', 'property_identifier'}}
        names = {ir_slice.target_callable.name}
        names.update(container.name for container in ir_slice.related_containers
                     if container.id == ir_slice.target_callable.container_id)
        if not names.intersection(identifiers):
            errors.append('Tests must reference the selected callable or its owning class.')
        return errors

    @staticmethod
    def validate_flow_tests(language: str, tests: GeneratedTestSuite) -> list[str]:
        expected = 'pytest' if language == 'python' else 'jest'
        errors = []
        if tests.framework.lower() != expected:
            errors.append(f'Test framework must be {expected}.')
        parser, _ = get_parser(language)
        tree = parser.parse(tests.test_code.encode())
        if tree.root_node.has_error:
            errors.append('Generated tests contain syntax errors.')
        if 'source_target' not in tests.test_code:
            errors.append('Import the module under test from source_target.')
        if not tests.test_case_names:
            errors.append('Provide names for the generated test cases.')
        for scenario in tests.scenarios:
            if scenario.name not in tests.test_case_names:
                errors.append('Each simulated scenario must match a generated test case name.')
        if {case.name for case in tests.scenarios} != set(tests.test_case_names):
            errors.append('Provide a simulated scenario for every generated test case.')
        return errors

    @staticmethod
    def validate_uml_span_integrity(ir: ProgramIR) -> list[str]:
        items = [*ir.symbols.callables, *ir.symbols.containers, *ir.symbols.variables,
                 *ir.dependencies, *ir.edges.calls, *ir.edges.data_flows, *ir.edges.type_relations]
        return [f'Missing source span: {item.id}' for item in items if item.span is None]

    @classmethod
    def audit_all(cls, ir: ProgramIR, ir_slice: IRSlice, language_id: str, feynman_explanation: str,
                  annotated_code: str, walkthrough: str, prerequisites: list[str]) -> QAGateResult:
        errors = cls.validate_pedagogical_completeness(language_id, feynman_explanation, annotated_code,
                                                      walkthrough, prerequisites, ir_slice)
        errors.extend(cls.validate_uml_span_integrity(ir))
        return QAGateResult(passed=not errors, errors=errors)

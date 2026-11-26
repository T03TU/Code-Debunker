"""Integration checks use mocked generation/execution; submitted code never runs on host."""
import asyncio
import json
import logging

import httpx
from instructor.core import InstructorRetryException
from instructor.core.exceptions import FailedAttempt
from openai import APITimeoutError

from fastapi.testclient import TestClient
import pytest

from app import main as api
from app import llm_settings
from app.models.llm import DebunkResponse, GeneratedTestSuite, PrerequisiteConcept, SimulatedTestCase
from app.sandbox.runner import SandboxExecutionResult

SOURCE = 'def double(value: int = 2) -> int:\n    return value * 2\n'
FLOW_SOURCE = SOURCE + '''
def add_fee(value):
    return double(value) + 1

def main(value):
    return add_fee(value)
'''
ANNOTATED = '''def double(value: int = 2) -> int:
    """Double a value.

    Args:
        value (int, optional): Input value. Defaults to 2.
    Returns:
        int: Twice the input value.
    """
    # Multiply the input by two.
    return value * 2
'''


def debunk(code=ANNOTATED):
    return DebunkResponse(language_identification='Python, imperative/functional',
                          feynman_explanation='double is like making two identical copies of an amount.',
                          annotated_code=code, simulated_walkthrough='For value=2, multiply by 2 and return 4.',
                          prerequisite_concepts=[PrerequisiteConcept(name=name, explanation='Used in double.')
                                                 for name in ['Functions', 'Parameters', 'Arithmetic']])


def suite():
    return GeneratedTestSuite(language='python', framework='pytest',
                              test_code='from source_target import double\n\ndef test_double():\n    assert double(2) == 4\n',
                              mock_summary='No external imports.', test_case_names=['test_double'],
                              purpose='Check that double multiplies its input by two.',
                              scenarios=[SimulatedTestCase(name='test_double', category='happy_path', input='2',
                                                           expected_output='4', predicted_output='4',
                                                           steps=['Multiply 2 by 2.', 'Return 4.'],
                                                           rationale='Covers a typical positive input.')])


def flow_suite():
    return GeneratedTestSuite(
        language='python', framework='pytest', mock_summary='No external imports.',
        test_code='from source_target import main\n\ndef test_checkout():\n    assert main(2) == 5\n',
        test_case_names=['test_checkout'], purpose='Check the total including the fee.',
        scenarios=[SimulatedTestCase(name='test_checkout', category='happy_path', input='main(2)',
                                    expected_output='5', predicted_output='5',
                                    steps=['main passes 2 to add_fee.', 'double returns 4.', 'add_fee returns 5.'],
                                    rationale='Covers the flow from entry point through both helpers.')],
    )


@pytest.fixture
def client(monkeypatch, tmp_path):
    api._sessions.clear()
    monkeypatch.setattr(llm_settings, 'SETTINGS_PATH', tmp_path / 'llm-settings.json')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    with TestClient(api.app) as test_client:
        yield test_client
    api._sessions.clear()


def analyze(client, **extra):
    response = client.post('/api/analyze', json={'code': SOURCE, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_analysis_and_slice_without_key(client):
    result = analyze(client)
    assert result['ir']['metadata']['primary_language'] == 'python'
    target = result['entry_point_symbol_id']
    response = client.get(f"/api/slice/{result['analysis_id']}", params={'symbol_id': target})
    assert response.status_code == 200
    assert response.json()['slice']['target_symbol_id'] == target
    for diagram in [result['class_diagram'], response.json()['dataflow_diagram']]:
        ids = {node['id'] for node in diagram['nodes']}
        assert all(edge['source'] in ids and edge['target'] in ids for edge in diagram['edges'])
        assert all(node['data']['span'] for node in diagram['nodes'])


@pytest.mark.parametrize('payload', [{'code': '   '}, {'code': ''}, {'code': SOURCE, 'language': 'ruby'},
                                     {'code': 'package main\nfunc main() {}', 'filename': 'main.go'}])
def test_invalid_input_is_actionable(client, payload):
    assert client.post('/api/analyze', json=payload).status_code == 422


def test_detects_javascript_without_python_filename_default(client):
    result = analyze(client, code='export function double(value) { return value * 2; }')
    assert result['ir']['metadata']['primary_language'] == 'javascript'
    assert result['ir']['symbols']['callables'][0]['name'] == 'double'


def test_unknown_target_never_falls_back(client):
    result = analyze(client)
    path = f"/api/slice/{result['analysis_id']}"
    response = client.get(path, params={'symbol_id': 'does-not-exist'})
    assert response.status_code == 422
    assert 'not found' in response.json()['detail']


def test_empty_callable_analysis_has_no_slice(client):
    result = analyze(client, code='answer = 42\n')
    assert result['dataflow_diagram'] is None
    assert client.get(f"/api/slice/{result['analysis_id']}").status_code == 422


def test_missing_key_rejected_before_stream_opens(client):
    result = analyze(client)
    response = client.get(f"/api/stream/{result['analysis_id']}")
    assert response.status_code == 503
    assert 'LLM settings' in response.json()['detail']


def test_missing_and_expired_sessions(client, monkeypatch):
    assert client.get('/api/slice/missing').status_code == 404
    result = analyze(client)
    api._sessions[result['analysis_id']]['created_at'] -= api.SESSION_TTL + 1
    assert client.get(f"/api/slice/{result['analysis_id']}").status_code == 404


def test_session_store_is_bounded(client, monkeypatch):
    monkeypatch.setattr(api, 'MAX_SESSIONS', 2)
    first = analyze(client)
    analyze(client)
    analyze(client)
    assert len(api._sessions) == 2
    assert first['analysis_id'] not in api._sessions


def test_stream_retries_invalid_annotation_before_emitting(client, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key-not-real')
    attempts = []

    async def generate(ir_slice, feedback=None, settings=None):
        attempts.append(feedback)
        return debunk(ANNOTATED.replace('return value * 2', 'return value * 3')) if len(attempts) == 1 else debunk()

    async def generate_tests(ir_slice, feedback=None, settings=None, explanation=None):
        return suite()

    monkeypatch.setattr(api, 'generate_debunk_async', generate)
    monkeypatch.setattr(api, 'generate_tests_async', generate_tests)
    result = analyze(client)
    response = client.get(f"/api/stream/{result['analysis_id']}")
    assert response.status_code == 200
    assert len(attempts) == 2
    assert 'executable logic' in attempts[1]
    assert 'value * 3' not in response.text
    assert response.text.count('event: section') == 5
    assert 'event: done' in response.text
    assert '"passed": true' in response.text


def test_failed_validation_is_withheld_after_one_retry(client, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key-not-real')
    attempts = []

    async def invalid(ir_slice, feedback=None, settings=None):
        attempts.append(feedback)
        return debunk('def adjacent():\n    return 1\n')

    async def generate_tests(ir_slice, feedback=None, settings=None, explanation=None):
        return suite()

    monkeypatch.setattr(api, 'generate_debunk_async', invalid)
    monkeypatch.setattr(api, 'generate_tests_async', generate_tests)
    result = analyze(client)
    response = client.get(f"/api/stream/{result['analysis_id']}")
    assert len(attempts) == 2
    assert 'event: section' not in response.text
    assert 'event: error' in response.text
    assert 'Explanation failed validation after one retry' in response.text
    assert 'valid source defining the selected callable' in response.text
    assert api._sessions[result['analysis_id']]['debunks'] == {}


def test_local_model_generates_explanation_before_tests(client, monkeypatch):
    client.post('/api/llm-settings', json={'provider': 'ollama', 'model': 'local', 'output_mode': 'json'})
    calls = []

    async def generate(ir_slice, feedback=None, settings=None):
        calls.append('explanation started')
        await asyncio.sleep(0)
        assert calls == ['explanation started']
        calls.append('explanation completed')
        return debunk()

    async def generate_tests(ir_slice, feedback=None, settings=None, explanation=None):
        assert calls == ['explanation started', 'explanation completed']
        assert explanation == debunk()
        calls.append('tests')
        return suite()

    monkeypatch.setattr(api, 'generate_debunk_async', generate)
    monkeypatch.setattr(api, 'generate_tests_async', generate_tests)
    result = analyze(client)
    response = client.get(f"/api/stream/{result['analysis_id']}")
    assert 'event: done' in response.text
    assert calls == ['explanation started', 'explanation completed', 'tests']


def test_hosted_provider_still_generates_artifacts_concurrently(client, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key-not-real')
    tests_started = None

    async def generate(ir_slice, feedback=None, settings=None):
        nonlocal tests_started
        tests_started = asyncio.Event()
        await asyncio.wait_for(tests_started.wait(), timeout=1)
        return debunk()

    async def generate_tests(ir_slice, feedback=None, settings=None, explanation=None):
        tests_started.set()
        return suite()

    monkeypatch.setattr(api, 'generate_debunk_async', generate)
    monkeypatch.setattr(api, 'generate_tests_async', generate_tests)
    result = analyze(client)
    assert 'event: done' in client.get(f"/api/stream/{result['analysis_id']}").text


def test_wrapped_generation_timeout_is_actionable_and_hides_provider_details(client, monkeypatch, caplog):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key-not-real')

    async def generate(ir_slice, feedback=None, settings=None):
        timeout = APITimeoutError(request=httpx.Request('POST', 'https://provider.example'))
        raise InstructorRetryException('Authorization: private-provider-key', n_attempts=1, total_usage=None,
                                       failed_attempts=[FailedAttempt(1, timeout)])

    async def generate_tests(ir_slice, feedback=None, settings=None, explanation=None):
        return suite()

    monkeypatch.setattr(api, 'generate_debunk_async', generate)
    monkeypatch.setattr(api, 'generate_tests_async', generate_tests)
    result = analyze(client)
    with caplog.at_level(logging.WARNING):
        response = client.get(f"/api/stream/{result['analysis_id']}")
    assert 'Explanation generation timed out' in response.text
    assert 'event: section' not in response.text
    assert 'private-provider-key' not in response.text
    assert 'private-provider-key' not in caplog.text


def test_valid_explanation_is_kept_when_test_generation_fails(client, monkeypatch):
    client.post('/api/llm-settings', json={'provider': 'ollama', 'model': 'local', 'output_mode': 'json'})

    async def generate(ir_slice, feedback=None, settings=None):
        return debunk()

    async def generate_tests(ir_slice, feedback=None, settings=None, explanation=None):
        raise TimeoutError('private-provider-key')

    monkeypatch.setattr(api, 'generate_debunk_async', generate)
    monkeypatch.setattr(api, 'generate_tests_async', generate_tests)
    result = analyze(client)
    response = client.get(f"/api/stream/{result['analysis_id']}")
    assert response.text.count('event: section') == 5
    assert 'Tests generation timed out' in response.text
    assert 'private-provider-key' not in response.text
    assert 'event: done' not in response.text


def test_generate_function_cases_without_explanation_or_docker(client, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key-not-real')
    result = analyze(client, code=FLOW_SOURCE)
    target = next(fn['id'] for fn in result['ir']['symbols']['callables'] if fn['name'] == 'double')
    generated_targets = []

    def unexpected_docker_call(self):
        pytest.fail('Test generation should not check Docker')

    async def generate_tests(ir_slice, feedback=None, settings=None, explanation=None):
        generated_targets.append(ir_slice.target_symbol_id)
        assert explanation is None
        return suite()

    monkeypatch.setattr(api.DockerSandboxRunner, 'availability', unexpected_docker_call)
    monkeypatch.setattr(api, 'generate_tests_async', generate_tests)
    path = f"/api/tests/{result['analysis_id']}"
    payload = {'scope': 'function', 'target_symbol_id': target}
    response = client.post(path, json=payload)
    assert response.status_code == 200
    assert response.json()['scope'] == 'function'
    assert response.json()['target_symbol_id'] == target
    assert response.json()['suite'] == suite().model_dump()
    assert client.post(path, json=payload).json() == response.json()
    assert generated_targets == [target]


def test_flow_cases_use_full_source_and_have_a_separate_model_cache(client, monkeypatch):
    model = {'provider': 'ollama', 'model': 'first'}
    assert client.post('/api/llm-settings', json=model).status_code == 200
    calls = []

    async def generate_debunk(ir_slice, feedback=None, settings=None):
        return debunk()

    async def generate_tests(ir_slice, feedback=None, settings=None, explanation=None):
        return suite()

    async def generate_flow(ir, source_code, *, explanations, feedback=None, settings=None):
        calls.append((settings.model, explanations))
        assert source_code == FLOW_SOURCE
        assert {fn.name for fn in ir.symbols.callables} == {'main', 'add_fee', 'double'}
        return flow_suite()

    monkeypatch.setattr(api, 'generate_debunk_async', generate_debunk)
    monkeypatch.setattr(api, 'generate_tests_async', generate_tests)
    monkeypatch.setattr(api, 'generate_flow_tests_async', generate_flow)
    result = analyze(client, code=FLOW_SOURCE)
    analysis_id = result['analysis_id']
    target = next(fn['id'] for fn in result['ir']['symbols']['callables'] if fn['name'] == 'double')
    assert 'event: done' in client.get(f'/api/stream/{analysis_id}', params={'symbol_id': target}).text
    path = f'/api/tests/{analysis_id}'
    flow = {'scope': 'flow'}
    response = client.post(path, json=flow)
    assert response.status_code == 200
    assert response.json()['scope'] == 'flow'
    assert response.json()['target_symbol_id'] is None
    assert response.json()['suite'] == flow_suite().model_dump()
    assert client.post(path, json=flow).json() == response.json()
    assert client.post(path, json={'target_symbol_id': target}).json()['suite'] == suite().model_dump()
    assert calls == [('first', [debunk()])]

    assert client.post('/api/llm-settings', json={**model, 'model': 'second'}).status_code == 200
    assert client.post(path, json=flow).status_code == 200
    assert calls == [('first', [debunk()]), ('second', [])]


def test_flow_cases_support_source_without_functions(client, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key-not-real')

    async def generate_flow(ir, source_code, *, explanations, feedback=None, settings=None):
        assert ir.symbols.callables == []
        assert source_code == 'answer = 42\n'
        return suite().model_copy(update={
            'test_code': 'from source_target import answer\n\ndef test_answer():\n    assert answer == 42\n',
            'test_case_names': ['test_answer'], 'purpose': 'Check the module-level answer.',
            'scenarios': [SimulatedTestCase(name='test_answer', category='happy_path', input='Import the module.',
                                            expected_output='answer = 42', predicted_output='answer = 42',
                                            steps=['Assign 42 to answer.'], rationale='Checks module initialization.')],
        })

    monkeypatch.setattr(api, 'generate_flow_tests_async', generate_flow)
    result = analyze(client, code='answer = 42\n')
    path = f"/api/tests/{result['analysis_id']}"
    assert client.post(path, json={'scope': 'function'}).status_code == 422
    response = client.post(path, json={'scope': 'flow'})
    assert response.status_code == 200
    assert response.json()['suite']['scenarios'][0]['predicted_output'] == 'answer = 42'


def test_invalid_flow_cases_are_retried_and_not_cached(client, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key-not-real')
    attempts = []

    async def generate_flow(ir, source_code, *, explanations, feedback=None, settings=None):
        attempts.append(feedback)
        invalid = flow_suite()
        return invalid.model_copy(update={'scenarios': [invalid.scenarios[0].model_copy(
            update={'name': 'private-invalid-output'})]})

    monkeypatch.setattr(api, 'generate_flow_tests_async', generate_flow)
    result = analyze(client, code=FLOW_SOURCE)
    response = client.post(f"/api/tests/{result['analysis_id']}", json={'scope': 'flow'})
    assert response.status_code == 502
    assert attempts[0] is None and 'scenario' in attempts[1]
    assert len(attempts) == 2
    assert 'private-invalid-output' not in response.text
    assert api._sessions[result['analysis_id']]['tests'] == {}


def test_generate_cases_validates_scope_target_and_session(client):
    result = analyze(client)
    path = f"/api/tests/{result['analysis_id']}"
    assert client.post(path, json={'scope': 'unknown'}).status_code == 422
    assert client.post(path, json={'target_symbol_id': 'unknown'}).status_code == 422
    assert client.post(path, json={'scope': 'flow'}).status_code == 503
    api._sessions[result['analysis_id']]['created_at'] -= api.SESSION_TTL + 1
    assert client.post(path, json={'scope': 'flow'}).status_code == 404


def test_simulation_uses_selected_target_and_cached_validated_suite(client, monkeypatch):
    result = analyze(client)
    target = result['entry_point_symbol_id']
    api._sessions[result['analysis_id']]['tests'][(llm_settings.get_settings().fingerprint, target)] = suite()
    monkeypatch.setattr(api.DockerSandboxRunner, 'availability', lambda self: (True, 'ready'))
    calls = []

    def run(self, **kwargs):
        calls.append(kwargs)
        return SandboxExecutionResult(status='PASS', exit_code=0)

    monkeypatch.setattr(api.DockerSandboxRunner, 'run_tests', run)
    response = client.post(f"/api/simulate/{result['analysis_id']}", json={'target_symbol_id': target})
    assert response.status_code == 200
    assert response.json()['target_symbol_id'] == target
    assert calls[0]['source_code'] == SOURCE
    assert calls[0]['test_code'] == suite().test_code


def test_flow_execution_reuses_generated_suite(client, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key-not-real')
    generations = []

    async def generate_flow(ir, source_code, *, explanations, feedback=None, settings=None):
        generations.append(source_code)
        return flow_suite()

    def run(self, *, source_code, language, test_code):
        assert source_code == FLOW_SOURCE
        assert language == 'python'
        assert test_code == flow_suite().test_code
        return SandboxExecutionResult(status='PASS', exit_code=0)

    monkeypatch.setattr(api, 'generate_flow_tests_async', generate_flow)
    monkeypatch.setattr(api.DockerSandboxRunner, 'availability', lambda self: (True, 'ready'))
    monkeypatch.setattr(api.DockerSandboxRunner, 'run_tests', run)
    result = analyze(client, code=FLOW_SOURCE)
    analysis_id = result['analysis_id']
    payload = {'scope': 'flow'}
    assert client.post(f'/api/tests/{analysis_id}', json=payload).status_code == 200
    response = client.post(f'/api/simulate/{analysis_id}', json=payload)
    assert response.status_code == 200
    assert response.json()['target_symbol_id'] is None
    assert response.json()['scope'] == 'flow'
    assert response.json()['execution']['status'] == 'PASS'
    assert generations == [FLOW_SOURCE]


def test_docker_unavailable_gives_setup_error_before_generation(client, monkeypatch):
    monkeypatch.setattr(api.DockerSandboxRunner, 'availability', lambda self: (False, 'Build runner image'))
    result = analyze(client)
    response = client.post(f"/api/simulate/{result['analysis_id']}", json={})
    assert response.status_code == 503
    assert response.json()['detail'] == 'Build runner image'


def test_capabilities_do_not_require_credentials_or_docker(client, monkeypatch):
    monkeypatch.setattr(api.DockerSandboxRunner, 'availability', lambda self: (False, 'unavailable'))
    response = client.get('/api/capabilities')
    assert response.status_code == 200
    assert response.json()['llm_configured'] is False
    assert response.json()['sandbox_available'] is False
    assert client.get('/health').json()['status'] == 'ok'

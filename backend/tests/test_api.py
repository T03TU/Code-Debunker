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
from app.models.llm import DebunkResponse, GeneratedTestSuite, PrerequisiteConcept
from app.sandbox.runner import SandboxExecutionResult

SOURCE = 'def double(value: int = 2) -> int:\n    return value * 2\n'
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
                              mock_summary='No external imports.', test_case_names=['test_double'])


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

    async def generate_tests(ir_slice, feedback=None, settings=None):
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

    async def generate_tests(ir_slice, feedback=None, settings=None):
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

    async def generate_tests(ir_slice, feedback=None, settings=None):
        assert calls == ['explanation started', 'explanation completed']
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

    async def generate_tests(ir_slice, feedback=None, settings=None):
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

    async def generate_tests(ir_slice, feedback=None, settings=None):
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

    async def generate_tests(ir_slice, feedback=None, settings=None):
        raise TimeoutError('private-provider-key')

    monkeypatch.setattr(api, 'generate_debunk_async', generate)
    monkeypatch.setattr(api, 'generate_tests_async', generate_tests)
    result = analyze(client)
    response = client.get(f"/api/stream/{result['analysis_id']}")
    assert response.text.count('event: section') == 5
    assert 'Tests generation timed out' in response.text
    assert 'private-provider-key' not in response.text
    assert 'event: done' not in response.text


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

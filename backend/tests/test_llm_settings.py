"""Settings lifecycle, credential isolation, routing, and structured generation checks."""
import asyncio
import json
import logging

from fastapi.testclient import TestClient
from instructor.core import InstructorRetryException
import pytest

from app import llm_settings as config
from app import main as api
from app.debunk import llm
from app.parser.graph_slicer import GraphSlicer
from app.parser.ir_builder import build_program_ir
from test_api import ANNOTATED, SOURCE, debunk, suite


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(config, 'SETTINGS_PATH', tmp_path / 'private' / 'llm-settings.json')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('OPENAI_BASE_URL', raising=False)
    monkeypatch.delenv('OPENAI_MODEL', raising=False)
    api._sessions.clear()
    with TestClient(api.app) as client:
        yield client
    api._sessions.clear()


def test_settings_roundtrip_private_persistence_and_credential_editing(client):
    payload = {'provider': 'openai', 'model': 'my-model', 'api_key': 'secret-one'}
    response = client.post('/api/llm-settings', json=payload)
    assert response.status_code == 200
    assert 'secret-one' not in response.text
    assert response.json()['saved_credentials']['api_key'] is True
    assert client.get('/api/llm-settings').json() == response.json()
    assert config.SETTINGS_PATH.stat().st_mode & 0o777 == 0o600
    assert config.SETTINGS_PATH.parent.stat().st_mode & 0o777 == 0o700
    assert json.loads(config.SETTINGS_PATH.read_text())['api_key'] == 'secret-one'
    assert not list(config.SETTINGS_PATH.parent.glob('.llm-*'))

    # Blank edits preserve credentials; an explicit replacement takes effect.
    assert client.post('/api/llm-settings', json={**payload, 'model': 'new-model', 'api_key': ''}).status_code == 200
    assert config.get_settings().api_key.get_secret_value() == 'secret-one'
    client.post('/api/llm-settings', json={**payload, 'api_key': 'secret-two'})
    assert config.get_settings().api_key.get_secret_value() == 'secret-two'


def test_settings_override_environment_without_changing_it(client, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'legacy-secret')
    monkeypatch.setenv('OPENAI_MODEL', 'legacy-model')
    assert client.get('/api/llm-settings').json()['model'] == 'legacy-model'
    assert 'legacy-secret' not in client.get('/api/llm-settings').text
    assert client.post('/api/llm-settings', json={'provider': 'ollama', 'model': 'local:latest', 'output_mode': 'json'}).status_code == 200
    assert config.get_settings().provider == 'ollama'
    assert not config.get_settings().api_key.get_secret_value()
    assert client.get('/api/capabilities').json()['llm_configured'] is True


@pytest.mark.parametrize('change', [{'provider': 'anthropic'}, {'base_url': 'https://different.example/v1'}])
def test_credentials_are_not_reused_for_another_service(client, change):
    payload = {'provider': 'openai', 'model': 'model', 'api_key': 'original-secret'}
    client.post('/api/llm-settings', json=payload)
    response = client.post('/api/llm-settings', json={**payload, **change, 'api_key': ''})
    assert response.status_code == 422
    assert config.get_settings().api_key.get_secret_value() == 'original-secret'


def test_forget_credentials_and_anonymous_local_endpoint(client):
    payload = {'provider': 'compatible', 'model': 'local', 'base_url': 'http://localhost:1234/v1', 'api_key': 'optional-key'}
    client.post('/api/llm-settings', json=payload)
    response = client.post('/api/llm-settings', json={**payload, 'api_key': '', 'clear_credentials': True})
    assert response.status_code == 200
    assert response.json()['saved_credentials']['api_key'] is False
    assert config.get_settings().completion_kwargs()['api_key'] == 'local-no-key'


@pytest.mark.parametrize('payload', [
    {'provider': 'unknown'}, {'model': ''}, {'base_url': 'file:///tmp/model'},
    {'base_url': 'https://user:secret-in-url@example.com/v1'},
    {'base_url': 'https://example.com/v1?key=secret-in-url'},
    {'base_url': 'http://[invalid'}, {'provider': 'azure', 'base_url': 'https://example.com'},
    {'provider': 'compatible'}, {'provider': 'custom', 'model': 'missing-provider'},
    {'vertex_credentials': 'invalid-secret-json'}, {'api_key': 'too-long-secret' * 3000},
])
def test_invalid_settings_never_echo_credentials(client, payload):
    response = client.post('/api/llm-settings', json={'api_key': 'submitted-secret', **payload})
    assert response.status_code == 422
    assert 'submitted-secret' not in response.text
    assert 'secret-in-url' not in response.text
    assert 'invalid-secret-json' not in response.text
    assert 'too-long-secret' not in response.text
    assert not config.SETTINGS_PATH.exists()


def test_test_connection_uses_unsaved_values_without_saving(client, monkeypatch):
    seen = []

    async def probe(settings):
        seen.append(settings)

    monkeypatch.setattr(api, 'test_connection', probe)
    response = client.post('/api/llm-settings/test', json={'provider': 'ollama', 'model': 'qwen:latest'})
    assert response.status_code == 200
    assert seen[0].model == 'qwen:latest'
    assert not config.SETTINGS_PATH.exists()


def test_provider_error_does_not_expose_credentials(client, monkeypatch, caplog):
    async def probe(settings):
        raise ValueError('Authorization: secret-provider-key')

    monkeypatch.setattr(api, 'test_connection', probe)
    with caplog.at_level(logging.DEBUG):
        response = client.post('/api/llm-settings/test', json={'api_key': 'secret-provider-key'})
    assert response.status_code == 502
    assert 'secret-provider-key' not in response.text
    assert 'secret-provider-key' not in caplog.text


def test_connection_timeout_explains_model_loading_without_exposing_details(client, monkeypatch):
    async def probe(settings):
        raise TimeoutError('Authorization: private-provider-key')

    monkeypatch.setattr(api, 'test_connection', probe)
    response = client.post('/api/llm-settings/test', json={'provider': 'ollama', 'model': 'qwen3.5:4b'})
    assert response.status_code == 504
    assert '90 seconds' in response.json()['detail']
    assert 'loading' in response.json()['detail']
    assert 'private-provider-key' not in response.text
    assert not config.SETTINGS_PATH.exists()


@pytest.mark.parametrize(('provider', 'model', 'extra', 'routed'), [
    ('openai', 'model', {'api_key': 'key'}, 'openai/model'),
    ('anthropic', 'claude', {'api_key': 'key'}, 'anthropic/claude'),
    ('gemini', 'gemini-model', {'api_key': 'key'}, 'gemini/gemini-model'),
    ('azure', 'deployment', {'api_key': 'key', 'api_version': 'version', 'base_url': 'https://resource.example'}, 'azure/deployment'),
    ('bedrock', 'profile.model', {'aws_region_name': 'region', 'aws_access_key_id': 'aws-key', 'aws_secret_access_key': 'aws-secret', 'aws_session_token': 'session'}, 'bedrock/profile.model'),
    ('vertex_ai', 'gemini-model', {'vertex_project': 'project', 'vertex_location': 'location', 'vertex_credentials': '{"type":"service_account"}'}, 'vertex_ai/gemini-model'),
    ('ollama', 'qwen:latest', {}, 'ollama_chat/qwen:latest'),
    ('lmstudio', 'org/model', {}, 'openai/org/model'),
    ('openrouter', 'company/model', {'api_key': 'key'}, 'openrouter/company/model'),
    ('compatible', 'org/model', {'base_url': 'http://127.0.0.1:1234/v1'}, 'openai/org/model'),
    ('custom', 'groq/company/model', {'api_key': 'key'}, 'groq/company/model'),
])
def test_provider_routing(provider, model, extra, routed):
    settings = config.LLMSettings(provider=provider, model=model, **extra)
    kwargs = settings.completion_kwargs()
    assert kwargs['model'] == routed
    for key, value in extra.items():
        assert kwargs['api_base' if key == 'base_url' else key] == value
    assert settings.configured


def test_full_local_generation_has_time_for_cpu_inference():
    for provider in ('ollama', 'lmstudio'):
        settings = config.LLMSettings(provider=provider, model='local-model')
        assert settings.completion_kwargs()['timeout'] == 600
        assert llm.connection_test_timeout(settings) == 90
    assert config.LLMSettings(provider='openai').completion_kwargs()['timeout'] == 90


def test_generation_context_includes_immediate_dependency_behavior_only():
    source = '''def checkout(items):
    return {"total": len(items)}

def unrelated():
    return "unrelated body must stay outside the slice"

def main():
    return checkout([1, 2])
'''
    ir_slice = GraphSlicer(build_program_ir(source)).extract_1hop_slice('main')
    context = llm._build_slice_context(ir_slice)
    assert ir_slice.target_callable.source_excerpt in context
    assert 'return {"total": len(items)}' in context
    assert 'unrelated body must stay outside the slice' not in context


def test_connection_probe_validates_real_instructor_output(monkeypatch):
    runtime = llm._provider_runtime()
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return runtime.ModelResponse(model=kwargs['model'], choices=[{'message': {
            'role': 'assistant', 'content': '{"reply":"connected"}'}, 'finish_reason': 'stop'}])

    monkeypatch.setattr(runtime, 'acompletion', complete)
    settings = config.LLMSettings(provider='compatible', model='org/local', base_url='http://127.0.0.1:1234/v1', output_mode='json')
    asyncio.run(llm.test_connection(settings))
    assert calls[0]['model'] == 'openai/org/local'
    assert calls[0]['api_base'] == settings.base_url
    assert calls[0]['response_format']['type'] == 'json_object'
    assert 'reasoning_effort' not in calls[0]


@pytest.mark.parametrize(('model', 'effort'), [('qwen3.5:4b', 'none'), ('gpt-oss:20b', 'low')])
def test_ollama_probe_uses_native_schema_and_controls_thinking(monkeypatch, model, effort):
    runtime = llm._provider_runtime()
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return runtime.ModelResponse(model=kwargs['model'], choices=[{'message': {
            'role': 'assistant', 'content': '{"reply":"connected"}'}, 'finish_reason': 'stop'}])

    monkeypatch.setattr(runtime, 'acompletion', complete)
    settings = config.LLMSettings(provider='ollama', model=model, output_mode='json')
    asyncio.run(llm.test_connection(settings))
    call = calls[0]
    schema = call['response_format']['json_schema']['schema']
    assert call['response_format']['type'] == 'json_schema'
    assert schema['properties']['reply']['type'] == 'string'
    assert 'reply' in schema['required']
    assert call['reasoning_effort'] == effort
    assert call['timeout'] > llm.connection_test_timeout(settings)
    # The schema belongs in Ollama's format field, rather than an extra system prompt.
    assert len(call['messages']) == 1
    assert call['messages'][0]['role'] == 'user'


def test_ollama_schema_still_rejects_invalid_model_output(monkeypatch):
    runtime = llm._provider_runtime()

    async def complete(**kwargs):
        return runtime.ModelResponse(model=kwargs['model'], choices=[{'message': {
            'role': 'assistant', 'content': '{"wrong_field":"connected"}'}, 'finish_reason': 'stop'}])

    monkeypatch.setattr(runtime, 'acompletion', complete)
    settings = config.LLMSettings(provider='ollama', model='qwen3.5:4b', output_mode='json')
    with pytest.raises(InstructorRetryException, match='reply'):
        asyncio.run(llm.test_connection(settings))


def test_debunk_and_tests_use_selected_settings_and_instructor_schema(monkeypatch):
    runtime = llm._provider_runtime()
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        name = kwargs['tools'][0]['function']['name']
        output = debunk() if name == 'DebunkResponse' else suite()
        return runtime.ModelResponse(model=kwargs['model'], choices=[{'message': {'role': 'assistant', 'content': None,
            'tool_calls': [{'id': 'call_1', 'type': 'function', 'function': {'name': name, 'arguments': output.model_dump_json()}}]},
            'finish_reason': 'tool_calls'}])

    monkeypatch.setattr(runtime, 'acompletion', complete)
    ir_slice = GraphSlicer(build_program_ir(SOURCE)).extract_1hop_slice()
    settings = config.LLMSettings(provider='anthropic', model='my-model', api_key='my-secret')
    result = asyncio.run(llm.generate_debunk_async(ir_slice, settings=settings))
    tests = asyncio.run(llm.generate_tests_async(ir_slice, settings=settings))
    assert result.annotated_code == ANNOTATED
    assert tests.test_code == suite().test_code
    assert all(call['model'] == 'anthropic/my-model' and call['api_key'] == 'my-secret' for call in calls)


def test_switching_models_regenerates_explanations_and_tests(client, monkeypatch):
    calls = []

    async def generate(ir_slice, feedback=None, settings=None):
        calls.append(('debunk', settings.model))
        return debunk()

    async def generate_tests(ir_slice, feedback=None, settings=None):
        calls.append(('tests', settings.model))
        return suite()

    monkeypatch.setattr(api, 'generate_debunk_async', generate)
    monkeypatch.setattr(api, 'generate_tests_async', generate_tests)
    client.post('/api/llm-settings', json={'provider': 'ollama', 'model': 'first'})
    analysis_id = client.post('/api/analyze', json={'code': SOURCE}).json()['analysis_id']
    path = f'/api/stream/{analysis_id}'
    assert 'event: done' in client.get(path).text
    assert 'event: done' in client.get(path).text
    assert len(calls) == 2
    client.post('/api/llm-settings', json={'provider': 'ollama', 'model': 'second'})
    assert 'event: done' in client.get(path).text
    assert calls == [('debunk', 'first'), ('tests', 'first'), ('debunk', 'second'), ('tests', 'second')]


def test_corrupt_saved_settings_do_not_break_analysis(client):
    config.SETTINGS_PATH.parent.mkdir()
    config.SETTINGS_PATH.write_text('broken-json')
    assert client.get('/api/llm-settings').status_code == 200
    assert client.post('/api/analyze', json={'code': SOURCE}).status_code == 200


@pytest.mark.parametrize('path', ['/api/llm-settings', '/api/llm-settings/test'])
def test_settings_reject_cross_origin_changes(client, path):
    response = client.post(path, json={'provider': 'ollama', 'model': 'local'},
                           headers={'Origin': 'https://unrelated.example'})
    assert response.status_code == 403
    assert not config.SETTINGS_PATH.exists()


def test_simple_openai_settings_remain_readable(client):
    config.SETTINGS_PATH.parent.mkdir()
    config.SETTINGS_PATH.write_text(json.dumps({'model': 'existing-model',
        'base_url': 'https://provider.example/v1', 'api_key': 'existing-private-key'}))
    settings = client.get('/api/llm-settings')
    assert settings.status_code == 200
    assert settings.json()['provider'] == 'openai'
    assert settings.json()['model'] == 'existing-model'
    assert settings.json()['saved_credentials']['api_key'] is True
    assert 'existing-private-key' not in settings.text

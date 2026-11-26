"""Check Docker contracts with mocks; submitted code never executes on the host."""
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from requests.exceptions import ReadTimeout

from app.sandbox.runner import DockerSandboxRunner, REPORT_MARKER


@pytest.fixture
def docker_client(monkeypatch):
    client = Mock()
    container = client.containers.run.return_value
    container.wait.return_value = {'StatusCode': 0}
    report = {'tests': [{'nodeid': 'test_target.py::test_double', 'outcome': 'passed', 'call': {'duration': 0.01}}]}
    container.logs.return_value = (REPORT_MARKER + json.dumps(report)).encode()
    monkeypatch.setattr('app.sandbox.runner.docker.from_env', lambda **kwargs: client)
    return client, container


def test_hardened_container_contract_and_staging_cleanup(docker_client):
    client, container = docker_client
    staged = []
    def start(**kwargs):
        directory = next(iter(kwargs['volumes']))
        staged.append(directory)
        assert Path(directory, 'source_target.py').read_text() == 'source fixture'
        assert Path(directory, 'test_target.py').read_text() == 'test fixture'
        assert kwargs['volumes'][directory]['mode'] == 'ro'
        assert kwargs['command'] == ['python', '-u', '/opt/runner/run.py', 'python']
        assert kwargs['network_mode'] == 'none'
        assert kwargs['read_only'] is True
        assert kwargs['tmpfs']['/tmp'] == 'rw,noexec,nosuid,size=64m'
        assert kwargs['cap_drop'] == ['ALL']
        assert kwargs['security_opt'] == ['no-new-privileges']
        assert kwargs['pids_limit'] == 64
        assert kwargs['mem_limit'] == '256m'
        assert kwargs['nano_cpus'] == 500_000_000
        assert kwargs['user'] == '1000:1000'
        return container
    client.containers.run.side_effect = start
    result = DockerSandboxRunner().run_tests('source fixture', 'test fixture', source_filename='../../evil;echo.py')
    assert result.status == 'PASS'
    assert result.tests[0].name == 'test_double'
    assert not Path(staged[0]).exists()
    container.remove.assert_called_once_with(force=True)
    container.wait.assert_called_once_with(timeout=10)
    client.close.assert_called_once()


def test_timeout_kills_and_removes_container(docker_client):
    _, container = docker_client
    container.wait.side_effect = ReadTimeout('test timeout')
    result = DockerSandboxRunner(timeout_seconds=99).run_tests('', '')
    assert result.status == 'TIMEOUT'
    container.kill.assert_called_once()
    container.remove.assert_called_once_with(force=True)
    assert container.wait.call_args.kwargs['timeout'] == 10


def test_daemon_unavailable_returns_error(monkeypatch):
    def unavailable(**kwargs):
        raise RuntimeError('no docker')
    monkeypatch.setattr('app.sandbox.runner.docker.from_env', unavailable)
    result = DockerSandboxRunner().run_tests('', '')
    assert result.status == 'ERROR'
    assert 'Docker' in result.stderr


def test_exit_zero_without_report_never_passes(docker_client):
    _, container = docker_client
    container.logs.return_value = b'nothing ran'
    assert DockerSandboxRunner().run_tests('', '').status == 'ERROR'


def test_python_skips_and_setup_errors_preserved():
    report = {'tests': [{'nodeid': 'skipped', 'outcome': 'skipped'},
                        {'nodeid': 'broken', 'outcome': 'error', 'setup': {'crash': {'message': 'ImportError', 'lineno': 3}}}]}
    result = DockerSandboxRunner()._parse_output('', 1, 0.1, 'python', report)
    assert result.status == 'ERROR'
    assert result.tests[0].outcome == 'skipped'
    assert result.tests[1].message == 'ImportError'
    assert result.tests[1].line_number == 3


def test_jest_report_has_assertion_results_and_milliseconds():
    report = {'testResults': [{'assertionResults': [
        {'fullName': 'double happy path', 'title': 'happy path', 'status': 'passed', 'duration': 10},
        {'fullName': 'double boundary', 'title': 'boundary', 'status': 'failed', 'failureMessages': ['expected 4, got 6']},
        {'fullName': 'double later', 'title': 'later', 'status': 'pending'},
    ]}]}
    result = DockerSandboxRunner()._parse_output('', 1, 0.1, 'typescript', report)
    assert result.status == 'FAIL'
    assert result.tests[0].duration == 0.01
    assert result.tests[1].message == 'expected 4, got 6'
    assert result.tests[2].outcome == 'skipped'


@pytest.mark.parametrize('language,extension', [('javascript', 'js'), ('typescript', 'ts')])
def test_javascript_and_typescript_use_correct_test_filenames(docker_client, language, extension):
    client, container = docker_client
    def start(**kwargs):
        directory = next(iter(kwargs['volumes']))
        assert Path(directory, f'source_target.{extension}').exists()
        assert Path(directory, f'target.test.{extension}').exists()
        assert kwargs['command'][-1] == language
        return container
    client.containers.run.side_effect = start
    DockerSandboxRunner().run_tests('', '', language=language)

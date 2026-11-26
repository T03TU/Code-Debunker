"""Launcher logic tests never execute submitted source or generated test suites."""
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
from unittest.mock import Mock

import pytest


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PROJECT = Path(__file__).resolve().parents[2]
launcher = load_module('codedebunker_launcher', PROJECT / 'scripts/launcher.py')
installer = load_module('codedebunker_desktop', PROJECT / 'scripts/install_desktop.py')


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, 'ROOT', tmp_path)
    monkeypatch.setattr(launcher, 'RUNTIME', tmp_path / '.runtime')
    monkeypatch.setattr(launcher, 'VENV_PYTHON', tmp_path / 'backend/.venv/bin/python')
    launcher.prepare_runtime()
    return tmp_path


def make_frontend(root, *, built=True):
    frontend = root / 'frontend'
    (frontend / 'src').mkdir(parents=True)
    (frontend / 'public').mkdir()
    (frontend / 'src/App.tsx').write_text('source')
    (frontend / 'package.json').write_text('{}')
    (frontend / 'package-lock.json').write_text('{}')
    if built:
        (frontend / 'dist/assets').mkdir(parents=True)
        (frontend / 'dist/assets/app.js').write_text('asset')
        (frontend / 'dist/index.html').write_text('<script src="/assets/app.js"></script>')
    return frontend


def test_runtime_and_state_are_private(workspace):
    launcher.write_json(launcher.RUNTIME / 'example.json', {'ok': True})
    assert launcher.RUNTIME.stat().st_mode & 0o777 == 0o700
    assert (launcher.RUNTIME / 'example.json').stat().st_mode & 0o777 == 0o600
    assert launcher.read_json(launcher.RUNTIME / 'example.json') == {'ok': True}
    assert not list(launcher.RUNTIME.glob('*.tmp'))


@pytest.mark.parametrize('contents', ['not json', '[]', 'null'])
def test_corrupt_state_is_ignored(workspace, contents):
    state = launcher.RUNTIME / 'instance.json'
    state.write_text(contents)
    assert launcher.instance_state() == {}


@pytest.mark.parametrize('port', [-1, 0, 65536, True, '8000'])
def test_control_state_cannot_redirect_to_an_arbitrary_address(workspace, port):
    launcher.write_json(launcher.RUNTIME / 'instance.json', {'port': port, 'token': 'a' * 32})
    assert launcher.instance_state() == {}


def test_fresh_existing_build_needs_neither_node_nor_npm(workspace, monkeypatch):
    make_frontend(workspace)
    monkeypatch.setattr(launcher, 'command_path', lambda name: pytest.fail('No build tools should run'))
    launcher.ensure_frontend()
    assert launcher.read_json(launcher.RUNTIME / 'frontend.json')['source']
    launcher.ensure_frontend()


def test_missing_asset_does_not_count_as_a_valid_build(workspace):
    frontend = make_frontend(workspace)
    assert launcher.valid_frontend()
    (frontend / 'dist/assets/app.js').unlink()
    assert not launcher.valid_frontend()


def test_source_change_rebuilds_and_cache_avoids_repeated_setup(workspace, monkeypatch):
    frontend = make_frontend(workspace)
    launcher.ensure_frontend()
    (frontend / 'src/App.tsx').write_text('new source')
    monkeypatch.setattr(launcher, 'command_path', lambda name: '/tools/' + name)
    monkeypatch.setattr(launcher.subprocess, 'check_output', lambda *args, **kwargs: 'v22.0.0')
    commands = []
    monkeypatch.setattr(launcher, 'run_step', lambda command, **kwargs: commands.append(command))
    launcher.ensure_frontend()
    assert commands == [['/tools/node', '/tools/npm', 'ci', '--no-audit', '--no-fund'],
                        ['/tools/node', '/tools/npm', 'run', 'build']]
    launcher.ensure_frontend()
    assert len(commands) == 2
    (frontend / 'src/App.tsx').write_text('another edit')
    (frontend / 'node_modules/vite/bin').mkdir(parents=True)
    (frontend / 'node_modules/vite/bin/vite.js').write_text('vite')
    launcher.ensure_frontend()
    assert commands[-1] == ['/tools/node', '/tools/npm', 'run', 'build']
    assert len(commands) == 3


def test_changed_packages_require_npm_ci_again(workspace, monkeypatch):
    frontend = make_frontend(workspace)
    launcher.ensure_frontend()
    (frontend / 'package.json').write_text('{"changed": true}')
    monkeypatch.setattr(launcher, 'command_path', lambda name: '/tools/' + name)
    monkeypatch.setattr(launcher.subprocess, 'check_output', lambda *args, **kwargs: 'v22.0.0')
    commands = []
    monkeypatch.setattr(launcher, 'run_step', lambda command, **kwargs: commands.append(command))
    launcher.ensure_frontend()
    assert commands[0][2] == 'ci'


def test_old_node_version_has_an_actionable_error(workspace, monkeypatch):
    make_frontend(workspace, built=False)
    monkeypatch.setattr(launcher, 'command_path', lambda name: '/tools/' + name)
    monkeypatch.setattr(launcher.subprocess, 'check_output', lambda *args, **kwargs: 'v18.0.0')
    with pytest.raises(launcher.LaunchError, match='Node.js 20'):
        launcher.ensure_frontend()


def test_existing_python_environment_is_adopted_then_cached(workspace, monkeypatch):
    requirements = workspace / 'backend/requirements.txt'
    requirements.parent.mkdir()
    requirements.write_text('fastapi>=0.115')
    launcher.VENV_PYTHON.parent.mkdir(parents=True)
    launcher.VENV_PYTHON.write_text('python')
    probe = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(launcher.subprocess, 'run', probe)
    commands = []
    monkeypatch.setattr(launcher, 'run_step', lambda command, **kwargs: commands.append(command))
    launcher.ensure_backend()
    launcher.ensure_backend()
    assert probe.call_count == 1
    assert commands == []
    requirements.write_text('fastapi>=0.120')
    launcher.ensure_backend()
    assert commands[0][1:4] == ['-m', 'pip', 'install']


def test_missing_python_packages_trigger_installation(workspace, monkeypatch):
    (workspace / 'backend').mkdir()
    (workspace / 'backend/requirements.txt').write_text('fastapi')
    launcher.VENV_PYTHON.parent.mkdir(parents=True)
    launcher.VENV_PYTHON.write_text('python')
    monkeypatch.setattr(launcher.subprocess, 'run', lambda *args, **kwargs: Mock(returncode=1))
    commands = []
    monkeypatch.setattr(launcher, 'run_step', lambda command, **kwargs: commands.append(command))
    launcher.ensure_backend()
    assert commands[0][1:4] == ['-m', 'pip', 'install']


def test_already_running_instance_is_reused_without_setup(workspace, monkeypatch):
    record = {'port': 8123, 'token': 'a' * 32}
    monkeypatch.setattr(launcher, 'instance_state', lambda: record)
    monkeypatch.setattr(launcher, 'control', lambda record, **kwargs: True)
    monkeypatch.setattr(launcher.subprocess, 'Popen', lambda *args, **kwargs: pytest.fail('No new process needed'))
    browser = Mock(return_value=True)
    monkeypatch.setattr(launcher.webbrowser, 'open', browser)
    assert launcher.start() == 'http://127.0.0.1:8123'
    browser.assert_called_once_with('http://127.0.0.1:8123', new=2)


def test_control_uses_loopback_and_authentication(workspace, monkeypatch):
    response = Mock(status=200)
    response.read.return_value = b'{"application":"CodeDebunker"}'
    connection = Mock()
    connection.getresponse.return_value = response
    constructor = Mock(return_value=connection)
    monkeypatch.setattr(launcher.http.client, 'HTTPConnection', constructor)
    assert launcher.control({'port': 8000, 'token': 'a' * 32}, stop=True)
    constructor.assert_called_once_with('127.0.0.1', 8000, timeout=1)
    connection.request.assert_called_once_with('POST', '/api/launcher/stop',
                                                headers={'Authorization': 'Bearer ' + 'a' * 32})
    connection.close.assert_called_once()


def test_unrelated_process_is_never_considered_our_server(workspace, monkeypatch):
    response = Mock(status=200)
    response.read.return_value = b'{"application":"another app"}'
    connection = Mock()
    connection.getresponse.return_value = response
    monkeypatch.setattr(launcher.http.client, 'HTTPConnection', lambda *args, **kwargs: connection)
    assert not launcher.control({'port': 8000, 'token': 'a' * 32}, stop=True)


def test_desktop_entry_quotes_paths_and_has_a_stop_action():
    entry = installer.desktop_entry(Path('/tmp/My Project'))
    assert 'Exec="/tmp/My Project/CodeDebunker"' in entry
    assert 'Terminal=false' in entry
    assert 'Actions=Stop;' in entry
    assert ' --stop' in entry
    assert '%%' in installer.exec_argument('/tmp/100%/CodeDebunker')


def test_project_shortcut_does_not_write_outside_project(workspace, monkeypatch):
    monkeypatch.setattr(installer, 'ROOT', workspace)
    monkeypatch.setattr(installer.shutil, 'which', lambda name: None)
    files = installer.install(project_only=True)
    assert files == [workspace / 'CodeDebunker.desktop']
    assert files[0].stat().st_mode & 0o111


def test_relative_xdg_data_directory_is_rejected(monkeypatch):
    monkeypatch.setenv('XDG_DATA_HOME', 'relative/path')
    with pytest.raises(ValueError, match='absolute'):
        installer.destinations(project_only=False)


def test_snap_ide_installs_in_native_applications_directory(monkeypatch):
    home = Path.home()
    monkeypatch.setenv('XDG_DATA_HOME', str(home / 'snap/code/252/.local/share'))
    assert installer.destinations(project_only=False)[-1] == home / '.local/share/applications/codedebunker.desktop'


def test_custom_native_xdg_data_directory_is_respected(monkeypatch, tmp_path):
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    assert installer.destinations(project_only=False)[-1] == tmp_path / 'applications/codedebunker.desktop'

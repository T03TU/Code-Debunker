"""Opt-in lifecycle tests start only the trusted app, without browser windows."""
from concurrent.futures import ThreadPoolExecutor
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from urllib.parse import urlsplit

import pytest

PROJECT = Path(__file__).resolve().parents[2]
EXECUTABLE = PROJECT / 'CodeDebunker'
pytestmark = pytest.mark.skipif(os.environ.get('RUN_LAUNCHER_TESTS') != '1',
                                reason='Set RUN_LAUNCHER_TESTS=1 for real local startup tests')


def launch(*args):
    return subprocess.run([str(EXECUTABLE), *args], cwd='/tmp', capture_output=True, text=True, timeout=120)


def stop_app():
    result = launch('--stop', '--no-browser')
    assert result.returncode == 0, result.stderr


@pytest.fixture(autouse=True)
def cleanup():
    stop_app()
    yield
    stop_app()


def request(url, path, *, method='GET'):
    connection = http.client.HTTPConnection('127.0.0.1', urlsplit(url).port, timeout=10)
    try:
        connection.request(method, path)
        response = connection.getresponse()
        return response.status, response.read().decode()
    finally:
        connection.close()


def test_launch_from_any_directory_and_repeated_clicks_share_one_instance():
    result = launch('--no-browser')
    assert result.returncode == 0, result.stderr
    url = result.stdout.strip()
    state_file = PROJECT / '.runtime/instance.json'
    before = json.loads(state_file.read_text())
    assert request(url, '/')[0] == 200
    assert json.loads(request(url, '/health')[1])['status'] == 'ok'
    with ThreadPoolExecutor(max_workers=3) as executor:
        repeated = list(executor.map(lambda _: launch('--no-browser'), range(3)))
    assert all(item.returncode == 0 and item.stdout.strip() == url for item in repeated)
    assert json.loads(state_file.read_text()) == before
    assert launch('--status').stdout.strip() == url
    assert state_file.stat().st_mode & 0o777 == 0o600


def test_unauthorized_stop_is_rejected_and_authorized_stop_cleans_state():
    result = launch('--no-browser')
    assert result.returncode == 0, result.stderr
    url = result.stdout.strip()
    assert request(url, '/api/launcher/stop', method='POST')[0] == 403
    assert request(url, '/health')[0] == 200
    stop_app()
    assert launch('--status').returncode == 1
    assert not (PROJECT / '.runtime/instance.json').exists()


def test_busy_default_port_is_preserved_and_another_port_is_used():
    class OtherApp(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'unrelated app')

        def log_message(self, *args):
            pass
    try:
        other = ThreadingHTTPServer(('127.0.0.1', 8000), OtherApp)
    except OSError:
        pytest.skip('Another application already owns port 8000')
    thread = threading.Thread(target=other.serve_forever, daemon=True)
    thread.start()
    try:
        result = launch('--no-browser')
        assert result.returncode == 0, result.stderr
        assert urlsplit(result.stdout.strip()).port != 8000
        assert request(result.stdout.strip(), '/')[0] == 200
        assert request('http://127.0.0.1:8000', '/')[1] == 'unrelated app'
        stop_app()
        assert request('http://127.0.0.1:8000', '/')[1] == 'unrelated app'
    finally:
        other.shutdown()
        other.server_close()
        thread.join(timeout=5)

#!/usr/bin/env python3
"""Linux desktop launcher and supervisor; no third-party bootstrap dependencies.

Only trusted application/setup commands run on the host. Submitted source and
its generated tests continue to execute exclusively in the Docker sandbox.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
from html.parser import HTMLParser
import http.client
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'
VENV_PYTHON = ROOT / 'backend/.venv/bin/python'
START_TIMEOUT = 900
PROBE_IMPORTS = (
    'import fastapi, uvicorn, pydantic, tree_sitter, tree_sitter_python, '
    'tree_sitter_javascript, tree_sitter_typescript, tree_sitter_go, '
    'tree_sitter_java, networkx, instructor, openai, docker, sse_starlette, dotenv; '
    'assert int(pydantic.__version__.split(".")[0]) >= 2'
)


class LaunchError(Exception):
    pass


def prepare_runtime() -> None:
    RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
    RUNTIME.chmod(0o700)


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as output:
            temporary.chmod(0o600)
            json.dump(value, output)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def progress(message: str, *, error: bool = False) -> None:
    print(message, flush=True)
    write_json(RUNTIME / 'progress.json', {'message': message, 'error': error})


def command_path(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    # Desktop sessions often lack the PATH additions from interactive shells.
    candidates = [Path('/usr/local/bin') / name, Path('/home/linuxbrew/.linuxbrew/bin') / name,
                  Path.home() / '.local/bin' / name]
    if name in {'node', 'npm'}:
        candidates.extend(sorted((Path.home() / '.nvm/versions/node').glob(f'*/bin/{name}'), reverse=True))
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise LaunchError(f'{name} is needed for initial setup. Install it, then open CodeDebunker again.')


def run_step(command: list[str], *, cwd: Path, description: str) -> None:
    progress(description)
    environment = os.environ.copy()
    environment['PIP_DISABLE_PIP_VERSION_CHECK'] = '1'
    # npm's executable uses /usr/bin/env node, including in GUI sessions.
    environment['PATH'] = str(Path(command[0]).parent) + os.pathsep + environment.get('PATH', '')
    child = subprocess.Popen(command, cwd=cwd, env=environment, start_new_session=True)
    try:
        if child.wait() != 0:
            raise LaunchError(f'{description} failed. Details are in {RUNTIME / "launcher.log"}.')
    except BaseException:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGTERM)
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
        raise


def digest(paths: list[Path]) -> str:
    result = hashlib.sha256()
    for path in sorted(paths):
        result.update(str(path.relative_to(ROOT)).encode())
        result.update(b'\0')
        result.update(path.read_bytes())
    return result.hexdigest()


def backend_source_digest() -> str:
    """Identify the code loaded by a worker, separately from dependency setup."""
    files = list((ROOT / 'backend/app').rglob('*.py'))
    files.extend(path for path in (ROOT / 'backend/requirements.txt', ROOT / 'scripts/launcher.py')
                 if path.is_file())
    return digest(files)


def ensure_backend() -> None:
    requirements = ROOT / 'backend/requirements.txt'
    expected = digest([requirements])
    marker = RUNTIME / 'backend.json'
    previous = read_json(marker)
    if not VENV_PYTHON.is_file():
        run_step([sys.executable, '-m', 'venv', str(VENV_PYTHON.parent.parent)],
                 cwd=ROOT, description='Creating the Python environment')
    identity = str(VENV_PYTHON.resolve()) + ':' + str(VENV_PYTHON.stat().st_mtime_ns)
    if previous == {'requirements': expected, 'python': identity}:
        return
    progress('Checking Python dependencies')
    existing = subprocess.run([str(VENV_PYTHON), '-c', PROBE_IMPORTS], cwd=ROOT / 'backend',
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    if not existing or (previous and previous.get('requirements') != expected):
        run_step([str(VENV_PYTHON), '-m', 'pip', 'install', '-r', str(requirements)],
                 cwd=ROOT, description='Installing Python dependencies (first launch may take a few minutes)')
    write_json(marker, {'requirements': expected, 'python': identity})


def frontend_inputs() -> list[Path]:
    frontend = ROOT / 'frontend'
    files = [path for directory in ('src', 'public') for path in (frontend / directory).rglob('*') if path.is_file()]
    files.extend(frontend / name for name in (
        'package.json', 'package-lock.json', 'index.html', 'vite.config.ts', 'tsconfig.json',
        'tsconfig.node.json', 'tailwind.config.js', 'postcss.config.js',
    ) if (frontend / name).is_file())
    return files


class AssetReferences(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.paths: list[str] = []

    def handle_starttag(self, tag: str, attributes: list[tuple[str, str | None]]) -> None:
        values = dict(attributes)
        reference = values.get('src') if tag == 'script' else values.get('href') if tag == 'link' else None
        if reference and reference.startswith('/') and not reference.startswith('//'):
            self.paths.append(reference.split('?', 1)[0].lstrip('/'))


def valid_frontend() -> bool:
    dist = ROOT / 'frontend/dist'
    try:
        parser = AssetReferences()
        parser.feed((dist / 'index.html').read_text())
        return bool(parser.paths) and all((dist / reference).is_file() for reference in parser.paths)
    except OSError:
        return False


def ensure_frontend() -> None:
    files = frontend_inputs()
    expected = digest(files)
    marker = RUNTIME / 'frontend.json'
    previous = read_json(marker)
    if valid_frontend():
        # Adopt an existing fresh build without forcing the first user to rebuild it.
        fresh = previous.get('source') == expected if previous else all(
            path.stat().st_mtime_ns <= (ROOT / 'frontend/dist/index.html').stat().st_mtime_ns for path in files)
        if fresh:
            write_json(marker, {'source': expected})
            return
    node = command_path('node')
    npm = command_path('npm')
    version = subprocess.check_output([node, '--version'], text=True).strip()
    if int(version.lstrip('v').split('.')[0]) < 20:
        raise LaunchError('Node.js 20 or newer is needed to build the app. Update Node.js and open CodeDebunker again.')
    frontend = ROOT / 'frontend'
    package_hash = digest([frontend / 'package.json', frontend / 'package-lock.json'])
    deps_marker = RUNTIME / 'frontend-dependencies.json'
    dependencies = read_json(deps_marker)
    if not (frontend / 'node_modules/vite/bin/vite.js').is_file() or dependencies.get('packages') != package_hash:
        # npm ci is deterministic and handles interrupted installations on the next launch.
        run_step([node, npm, 'ci', '--no-audit', '--no-fund'], cwd=frontend,
                 description='Installing frontend dependencies (first launch may take a few minutes)')
        write_json(deps_marker, {'packages': package_hash})
    run_step([node, npm, 'run', 'build'], cwd=frontend, description='Building the interface')
    if not valid_frontend():
        raise LaunchError('The interface build is incomplete. See .runtime/launcher.log.')
    write_json(marker, {'source': expected})


def instance_state() -> dict:
    record = read_json(RUNTIME / 'instance.json')
    if (type(record.get('port')) is not int or not 1 <= record['port'] <= 65535
            or not isinstance(record.get('token'), str) or len(record['token']) != 32):
        return {}
    return record


def control(record: dict, *, stop: bool = False) -> bool:
    if not record:
        return False
    connection = http.client.HTTPConnection('127.0.0.1', record['port'], timeout=1)
    try:
        connection.request('POST' if stop else 'GET', '/api/launcher/stop' if stop else '/api/launcher/status',
                           headers={'Authorization': 'Bearer ' + record['token']})
        response = connection.getresponse()
        data = json.loads(response.read(4096))
        return response.status == 200 and data.get('application') == 'CodeDebunker'
    except (OSError, ValueError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def supervisor_running() -> bool:
    with (RUNTIME / 'service.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
        return False


def worker() -> None:
    # This process uses backend/.venv/bin/python after setup is complete.
    source_digest = backend_source_digest()
    sys.path.insert(0, str(ROOT / 'backend'))
    from dotenv import load_dotenv
    load_dotenv(ROOT / 'backend/.env')
    import uvicorn
    from fastapi import FastAPI, Header, HTTPException
    from app.main import app

    wrapper = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    token = uuid.uuid4().hex
    server = uvicorn.Server(uvicorn.Config(wrapper, host='127.0.0.1', log_level='warning',
                                          timeout_graceful_shutdown=15))

    def authorize(authorization: str) -> None:
        import hmac
        if not hmac.compare_digest(authorization, 'Bearer ' + token):
            raise HTTPException(403, 'Launcher authorization required')

    @wrapper.get('/api/launcher/status')
    async def status(authorization: str = Header(default='')):
        authorize(authorization)
        return {'application': 'CodeDebunker'}

    @wrapper.post('/api/launcher/stop')
    async def stop(authorization: str = Header(default='')):
        authorize(authorization)
        server.should_exit = True
        return {'application': 'CodeDebunker'}

    wrapper.mount('/', app)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            listener.bind(('127.0.0.1', 8000))
        except OSError:
            listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
        listener.listen(128)
        write_json(RUNTIME / 'instance.json', {'port': port, 'token': token,
                                             'backend_source': source_digest})
        progress('Opening CodeDebunker')
        server.run(sockets=[listener])


def supervise() -> int:
    with (RUNTIME / 'service.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
        child = None
        try:
            def terminate(*_):
                raise KeyboardInterrupt
            signal.signal(signal.SIGTERM, terminate)
            progress('Preparing CodeDebunker')
            (RUNTIME / 'instance.json').unlink(missing_ok=True)
            ensure_backend()
            ensure_frontend()
            child = subprocess.Popen([str(VENV_PYTHON), str(Path(__file__).resolve()), '--worker'], cwd=ROOT)
            result = child.wait()
            if result:
                raise LaunchError('The app could not start. See .runtime/launcher.log.')
            return 0
        except KeyboardInterrupt:
            return 130
        except Exception as error:
            progress(str(error), error=True)
            return 1
        finally:
            if child is not None and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            (RUNTIME / 'instance.json').unlink(missing_ok=True)


class StartupDialog:
    def __init__(self, enabled: bool) -> None:
        self.process = None
        self.message = ''
        if enabled and shutil.which('zenity') and (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
            self.process = subprocess.Popen([
                'zenity', '--progress', '--pulsate', '--auto-close', '--no-cancel',
                '--title=CodeDebunker', '--text=Starting CodeDebunker…', '--width=440',
            ], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)

    def update(self, message: str) -> None:
        if self.process is not None and self.process.stdin and self.process.poll() is None and message != self.message:
            try:
                self.process.stdin.write('#' + message.replace('\n', ' ') + '\n')
                self.process.stdin.flush()
                self.message = message
            except BrokenPipeError:
                pass

    def close(self) -> None:
        if self.process is not None:
            if self.process.stdin:
                self.process.stdin.close()
            if self.process.poll() is None:
                self.process.terminate()
            self.process.wait()


def _start_instance(*, ui: bool) -> dict:
    record = instance_state()
    running = control(record)
    if running and record.get('backend_source') != backend_source_digest():
        progress('Updating the running backend')
        if not control(record, stop=True):
            raise LaunchError('The outdated app could not be stopped. Close CodeDebunker and try opening it again.')
        deadline = time.monotonic() + 20
        while supervisor_running():
            if time.monotonic() >= deadline:
                raise LaunchError('CodeDebunker is still stopping to apply an update. Try opening it again shortly.')
            time.sleep(0.1)
        running = False
    if not running:
        # The supervisor owns the process lock for the entire service lifetime.
        # Concurrent clicks can spawn candidates; exactly one candidate starts the app.
        log = RUNTIME / 'launcher.log'
        if not supervisor_running() and log.is_file() and log.stat().st_size > 1_000_000:
            log.replace(RUNTIME / 'launcher.previous.log')
        with log.open('a') as output:
            log.chmod(0o600)
            candidate = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--supervise'],
                                         cwd=ROOT, stdin=subprocess.DEVNULL, stdout=output, stderr=output,
                                         start_new_session=True)
        dialog = StartupDialog(ui)
        try:
            deadline = time.monotonic() + START_TIMEOUT
            while time.monotonic() < deadline:
                record = instance_state()
                if control(record):
                    break
                state = read_json(RUNTIME / 'progress.json')
                dialog.update(state.get('message', 'Starting CodeDebunker…'))
                if candidate.poll() is not None and not supervisor_running():
                    raise LaunchError(state.get('message') or 'Startup failed. See .runtime/launcher.log.')
                time.sleep(0.2)
            else:
                raise LaunchError('Startup is taking longer than expected. See .runtime/launcher.log and open CodeDebunker again.')
        finally:
            dialog.close()
    return record


def start(*, browser: bool = True, ui: bool = True) -> str:
    # Serialize reopening and updating so concurrent clicks cannot stop a newly
    # started worker or open the old worker while it is being replaced.
    with (RUNTIME / 'start.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        record = _start_instance(ui=ui)
    url = f'http://127.0.0.1:{record["port"]}'
    if browser and not webbrowser.open(url, new=2):
        raise LaunchError(f'The app is running at {url}, but the browser could not open. Open this address manually.')
    return url


def show_error(message: str, *, ui: bool) -> None:
    print(message, file=sys.stderr)
    if ui and shutil.which('zenity') and (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY')):
        subprocess.run(['zenity', '--error', '--title=CodeDebunker', '--no-markup', '--text=' + message], check=False)


def main() -> int:
    parser = argparse.ArgumentParser(description='Open CodeDebunker. Setup is automatic on first launch.')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--stop', action='store_true', help='Stop this project’s background app')
    mode.add_argument('--status', action='store_true', help='Print the running app URL')
    mode.add_argument('--supervise', action='store_true', help=argparse.SUPPRESS)
    mode.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--no-browser', action='store_true', help='Start without opening a browser or showing dialogs')
    args = parser.parse_args()
    try:
        if sys.version_info < (3, 11):
            raise LaunchError('CodeDebunker needs Python 3.11 or newer.')
        prepare_runtime()
        if args.worker:
            worker()
            return 0
        if args.supervise:
            return supervise()
        if args.stop:
            if control(instance_state(), stop=True):
                deadline = time.monotonic() + 20
                while supervisor_running() and time.monotonic() < deadline:
                    time.sleep(0.1)
                print('CodeDebunker is stopping.' if supervisor_running() else 'CodeDebunker stopped.')
                return 0
            if supervisor_running():
                raise LaunchError('CodeDebunker is still starting. Try stopping it after setup completes.')
            print('CodeDebunker is not running.')
            return 0
        if args.status:
            record = instance_state()
            if control(record):
                print(f'http://127.0.0.1:{record["port"]}')
                return 0
            print('CodeDebunker is not running.')
            return 1
        print(start(browser=not args.no_browser, ui=not args.no_browser))
        return 0
    except (LaunchError, OSError, subprocess.SubprocessError) as error:
        show_error(str(error), ui=not args.no_browser)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

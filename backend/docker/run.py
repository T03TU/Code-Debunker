"""Container-only test supervisor. This file never runs on the application host."""
import json
from pathlib import Path
import subprocess
import sys

language = sys.argv[1]
if language == 'python':
    command = ['python', '-m', 'pytest', '--json-report', '--json-report-file=/tmp/report.json',
               '-p', 'no:cacheprovider', '/workspace/test_target.py']
else:
    command = ['node', '/opt/runner/node_modules/jest/bin/jest.js', '--config',
               '/opt/runner/jest.config.cjs', '--runInBand', '--no-cache', '--json',
               '--outputFile=/tmp/report.json']
print('Starting isolated ' + ('pytest' if language == 'python' else 'Jest') + ' runner.', flush=True)
result = subprocess.run(command, check=False)
# tmpfs disappears when the container stops. Emit the structured report before exit.
report = Path('/tmp/report.json')
if report.is_file() and report.stat().st_size <= 512_000:
    try:
        payload = json.loads(report.read_text())
        print('\n__CODEDEBUNK_REPORT__' + json.dumps(payload), flush=True)
    except (ValueError, OSError):
        pass
sys.exit(result.returncode)

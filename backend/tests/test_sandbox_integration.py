"""Opt-in tests execute fixtures ONLY through the hardened Docker runner."""
import os

import pytest

from app.sandbox.runner import DockerSandboxRunner

pytestmark = pytest.mark.skipif(os.environ.get('RUN_SANDBOX_TESTS') != '1', reason='Set RUN_SANDBOX_TESTS=1 with Docker and the runner image available')


@pytest.mark.parametrize('language,source,tests', [
    ('python', 'def double(value):\n    return value * 2\n',
     'from source_target import double\n\ndef test_double():\n    assert double(2) == 4\n\ndef test_boundary():\n    assert double(0) == 0\n'),
    ('javascript', 'export function double(value) { return value * 2; }',
     "import { double } from './source_target';\ntest('double', () => expect(double(2)).toBe(4));\ntest('boundary', () => expect(double(0)).toBe(0));"),
    ('typescript', 'export function double(value: number): number { return value * 2; }',
     "import { double } from './source_target';\ntest('double', () => expect(double(2)).toBe(4));\ntest('boundary', () => expect(double(0)).toBe(0));"),
])
def test_language_runners_return_individual_results(language, source, tests):
    result = DockerSandboxRunner().run_tests(source, tests, language)
    assert result.status == 'PASS', result.model_dump()
    assert len(result.tests) == 2
    assert all(test.outcome == 'passed' for test in result.tests)


def test_assertion_failure_is_not_reported_as_harness_error():
    result = DockerSandboxRunner().run_tests('def broken():\n    return 3\n', 'from source_target import broken\n\ndef test_broken():\n    assert broken() == 4\n')
    assert result.status == 'FAIL', result.model_dump()
    assert result.tests[0].message


def test_timeout_and_read_only_workspace():
    result = DockerSandboxRunner(timeout_seconds=2).run_tests('', 'def test_loop():\n    while True:\n        pass\n')
    assert result.status == 'TIMEOUT', result.model_dump()
    result = DockerSandboxRunner().run_tests('', '''import pytest
from pathlib import Path

def test_workspace_is_read_only():
    with pytest.raises(OSError):
        Path('/workspace/source_target.py').write_text('modified')

def test_nonroot():
    import os
    assert os.getuid() == 1000
''')
    assert result.status == 'PASS', result.model_dump()

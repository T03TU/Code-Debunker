"""Run untrusted code only in resource-limited, ephemeral Docker containers."""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import time
from typing import Any, Literal

import docker
from pydantic import BaseModel, Field
from requests.exceptions import ReadTimeout, ConnectionError

DEFAULT_IMAGE = "codedebunk-runner:latest"
REPORT_MARKER = "__CODEDEBUNK_REPORT__"
logger = logging.getLogger('codedebunk.sandbox')


class TestCaseResult(BaseModel):
    nodeid: str
    name: str
    outcome: Literal["passed", "failed", "error", "skipped"]
    duration: float = 0.0
    message: str | None = None
    line_number: int | None = None


class SandboxExecutionResult(BaseModel):
    status: Literal["PASS", "FAIL", "ERROR", "TIMEOUT"]
    exit_code: int
    tests: list[TestCaseResult] = Field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0
    raw_report: dict[str, Any] | None = None


class DockerSandboxRunner:
    def __init__(self, image_name: str = DEFAULT_IMAGE, timeout_seconds: int = 10) -> None:
        self.image_name = image_name
        self.timeout_seconds = min(max(timeout_seconds, 1), 10)
        self._client: docker.DockerClient | None = None

    def _get_client(self) -> docker.DockerClient:
        if self._client is None:
            self._client = docker.from_env(timeout=5)
        return self._client

    def availability(self) -> tuple[bool, str]:
        try:
            client = self._get_client()
            client.ping()
            client.images.get(self.image_name)
            return True, "Sandbox ready"
        except Exception:
            return False, "Docker or the codedebunk-runner image is unavailable. See README for setup."
        finally:
            self.close()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def run_tests(
        self, source_code: str, test_code: str, language: str = "python",
        source_filename: str | None = None, test_filename: str | None = None,
    ) -> SandboxExecutionResult:
        started = time.monotonic()
        if language not in {"python", "javascript", "typescript"}:
            return SandboxExecutionResult(status="ERROR", exit_code=1, stderr="Unsupported test language")

        # Stable filenames are part of the generation contract. Never interpolate user
        # filenames into shell commands or allow source and test paths to collide.
        extension = {"python": "py", "javascript": "js", "typescript": "ts"}[language]
        source_filename = f"source_target.{extension}"
        test_filename = "test_target.py" if language == "python" else f"target.test.{extension}"
        staging_dir = tempfile.mkdtemp(prefix="codedebunk_sandbox_")
        container = None
        try:
            client = self._get_client()
            os.chmod(staging_dir, 0o755)
            for filename, content in ((source_filename, source_code), (test_filename, test_code)):
                path = os.path.join(staging_dir, filename)
                with open(path, "w", encoding="utf-8") as output:
                    output.write(content)
                os.chmod(path, 0o444)

            command = ["python", "-u", "/opt/runner/run.py", language]

            container = client.containers.run(
                image=self.image_name, command=command,
                volumes={staging_dir: {"bind": "/workspace", "mode": "ro"}},
                network_mode="none", read_only=True,
                tmpfs={"/tmp": "rw,noexec,nosuid,size=64m"},
                cap_drop=["ALL"], security_opt=["no-new-privileges"],
                pids_limit=64, mem_limit="256m", nano_cpus=500_000_000,
                user="1000:1000", working_dir="/workspace",
                environment={"PYTHONPATH": "/workspace", "PYTHONDONTWRITEBYTECODE": "1",
                             "NODE_PATH": "/opt/runner/node_modules", "HOME": "/tmp"},
                log_config=docker.types.LogConfig(type="json-file", config={"max-size": "1m", "max-file": "1"}),
                detach=True,
            )
            try:
                result = container.wait(timeout=self.timeout_seconds)
            except (ReadTimeout, ConnectionError) as error:
                if isinstance(error, ConnectionError) and 'timed out' not in str(error).lower():
                    raise
                container.kill()
                return SandboxExecutionResult(
                    status="TIMEOUT", exit_code=-1,
                    stderr=f"Execution exceeded {self.timeout_seconds} seconds.",
                    stdout=container.logs(tail=30).decode('utf-8', errors='replace')[:4000],
                    duration_seconds=time.monotonic() - started,
                )

            logs = container.logs(tail=200).decode("utf-8", errors="replace")
            report = None
            if REPORT_MARKER in logs:
                logs, payload = logs.rsplit(REPORT_MARKER, 1)
                try:
                    parsed = json.loads(payload)
                    report = parsed if isinstance(parsed, dict) else None
                except ValueError:
                    pass
            return self._parse_output(logs, result.get("StatusCode", 1),
                                      time.monotonic() - started, language, report)
        except Exception:
            logger.exception('Sandbox execution failed')
            return SandboxExecutionResult(
                status="ERROR", exit_code=1,
                stderr="Sandbox execution failed. Check Docker access and build the runner image (see README).",
                duration_seconds=time.monotonic() - started,
            )
        finally:
            if container is not None:
                try:
                    container.remove(force=True)
                except Exception:
                    pass
            self.close()
            shutil.rmtree(staging_dir, ignore_errors=True)

    def _parse_output(self, logs: str, exit_code: int, duration: float,
                      language: str, report: dict[str, Any] | None = None) -> SandboxExecutionResult:
        tests: list[TestCaseResult] = []
        if report is not None:
            if language == "python":
                for test in report.get("tests", []):
                    outcome = test.get("outcome", "error")
                    if outcome not in {"passed", "failed", "skipped"}:
                        outcome = "error"
                    phases = [test.get(phase, {}) for phase in ("setup", "call", "teardown")]
                    crash = next((phase["crash"] for phase in phases if phase.get("crash")), {})
                    tests.append(TestCaseResult(
                        nodeid=test.get("nodeid", ""), name=test.get("nodeid", "").split("::")[-1],
                        outcome=outcome, duration=sum(phase.get("duration", 0.0) for phase in phases),
                        message=crash.get("message"), line_number=crash.get("lineno"),
                    ))
            else:
                for suite in report.get("testResults", []):
                    for test in suite.get("assertionResults", []):
                        outcome = {"passed": "passed", "failed": "failed", "pending": "skipped",
                                   "todo": "skipped", "disabled": "skipped"}.get(test.get("status"), "error")
                        tests.append(TestCaseResult(
                            nodeid=test.get("fullName", ""), name=test.get("title", ""), outcome=outcome,
                            duration=(test.get("duration") or 0) / 1000,
                            message="\n".join(test.get("failureMessages", [])) or None,
                        ))

        # A successful process without any report/tests must never produce a PASS badge.
        if not report or not tests or any(t.outcome == "error" for t in tests):
            status = "ERROR"
        elif exit_code != 0 or any(t.outcome == "failed" for t in tests):
            status = "FAIL"
        elif any(t.outcome == "passed" for t in tests):
            status = "PASS"
        else:
            status = "ERROR"
        return SandboxExecutionResult(
            status=status, exit_code=exit_code, tests=tests, stdout=logs[:8000],
            stderr="Test runner did not produce a valid test report." if not report or not tests else "",
            duration_seconds=duration, raw_report=report,
        )

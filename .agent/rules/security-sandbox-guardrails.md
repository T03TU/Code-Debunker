---
trigger: always_on
description: Enforces strict zero-trust Docker isolation invariants whenever writing sandbox code or executing generated unit tests.
---

# Security & Sandbox Isolation Guardrails

Submitted source code is untrusted by default. Every execution path that runs user code or generated unit tests must obey these non-negotiable security invariants:

1. **No Host Execution:** Never execute submitted user code or generated test files via bare `subprocess`, `exec()`, `eval()`, or host `pytest`/`node` processes.
2. **Mandatory Container Hardening Flags:** Every Docker execution container must be launched with:
   - `--network none` (complete network isolation)
   - `--read-only` (immutable root filesystem)
   - `--tmpfs /tmp:rw,noexec,nosuid,size=64m` (writable temp space with execution disabled)
   - `--cap-drop ALL` and `--security-opt no-new-privileges`
   - `--pids-limit 64` (prevents fork bombs)
   - `--memory 256m` and `--cpus 0.5` (prevents resource exhaustion)
   - `--user 1000:1000` (non-root execution)
3. **Strict Execution Timeout:** Enforce a hard wall-clock timeout of **10 seconds**. Kill and remove (`docker rm -f`) the container immediately upon timeout or completion.
4. **Input Sanitization:** Strip path traversal sequences (`../`) before mounting code into `/workspace:ro` inside the container.
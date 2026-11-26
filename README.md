# CodeDebunker

A local code exploration workbench. Paste or upload Python, JavaScript, or TypeScript to inspect functions, variables, imports, class relationships, and data flow. Click diagram elements to highlight their source in Monaco. Select a function to generate a five-part explanation and run generated tests in Docker.

Structural analysis uses Tree-sitter and NetworkX; it needs neither an API key nor Docker and never executes submitted source.

## Run locally

Requires Python 3.11+, Node.js 20+, and npm. Docker is optional for structural analysis and explanations, and required for test execution.

Install dependencies from the project root:

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
```

Start both services:

```bash
./scripts/dev.sh
```

Open **http://127.0.0.1:5173**. The frontend proxies `/api` requests to the backend on port 8000. API documentation is at **http://127.0.0.1:8000/docs**. Stop both services with Ctrl+C.

To run services separately:

```bash
# Terminal 1, from backend/
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Terminal 2, from frontend/
CHOKIDAR_USEPOLLING=1 npm run dev -- --host 127.0.0.1
```

The polling option handles systems with exhausted file watchers.

## Explanations and generated tests

Copy `backend/.env.example` to `backend/.env` and set `OPENAI_API_KEY`. `OPENAI_MODEL` defaults to `gpt-4o` and can be changed to a model compatible with the existing Instructor/OpenAI integration. The startup script loads this file; for manual startup, pass `--env-file .env` to Uvicorn. Restart the backend after configuration changes. Credentials stay on the backend.

**Explain function** sends the selected callable's source and immediate dependency context to the configured OpenAI model. It generates language identification, a Feynman explanation, annotated code, an illustrative execution walkthrough, prerequisite concepts, and tests. It never sends the entire source file to the model. Structural validation runs before each generated artifact is emitted; one corrective retry receives the validation errors. The annotated target must preserve its executable tokens. These checks do not prove semantic correctness; use the actual test results to evaluate behavior.

## Isolated execution

Build the runner image from the project root:

```bash
docker build -f backend/docker/Dockerfile.runner -t codedebunk-runner:latest backend/docker
```

The backend user must have access to the Docker daemon. The image includes pytest with a JSON reporter and Jest with a TypeScript transformer. Source is mounted under the fixed name `source_target.py`, `source_target.js`, or `source_target.ts` so generated imports are consistent.

Each execution uses a disposable container with no network, a read-only root and source mount, a `noexec,nosuid` temporary filesystem, no Linux capabilities, no privilege escalation, UID/GID 1000, 64 processes, 256 MB memory, half a CPU, and a maximum 10-second execution wait. Containers and staging directories are removed after success, failure, or timeout. There is no host-execution fallback.

Test reports are emitted before container exit because temporary filesystem contents disappear when the container stops. Only actual reported tests can produce a PASS badge; an empty or missing report is an error. Reported outcomes map to the selected function in the diagram.

## Verification

```bash
cd backend
.venv/bin/python -m pytest -q

# Include real isolated execution tests; requires the image above.
RUN_SANDBOX_TESTS=1 .venv/bin/python -m pytest -q

cd ../frontend
npm run build
```

Verification for this milestone: **55 tests passed with real Docker execution enabled**, the TypeScript/Vite production build passed, and Chrome checks covered all three languages, function selection, diagrams, source invalidation, and mobile layout. Desktop and mobile captures are in `artifacts/`. Live model generation has not been exercised because no API key is configured.

Default tests mock model and Docker calls. Opt-in tests exercise real Python, JavaScript, and TypeScript runners, assertion failures, timeout cleanup, non-root execution, and read-only source mounts. Submitted source and generated tests execute only in Docker.

## Serve the production build locally

```bash
npm --prefix frontend run build
cd backend
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Build before starting the backend. FastAPI serves `frontend/dist` at **http://127.0.0.1:8000** when it exists. Monaco and its workers are bundled locally.

## Project state and remaining work

The Antigravity handoff contained a working parser/model foundation and eight passing tests, API and sandbox scaffolding, and an incomplete frontend with a missing `App` component. `.agents` was empty; the actual rules and specialist instructions were in `.agent`. The continued implementation adds the workbench and closes critical API, graph, validation, and sandbox integration gaps.

The current milestone supports **single source files and snippets**, up to 200 KB. It is a local workbench, with in-memory sessions that expire after an hour and a 100-session limit. Sessions disappear when the backend restarts; use one backend worker. It has no authentication and is not prepared for public deployment.

Further work toward the broader vision in `GEMINI.md`:

- Multi-file and repository ingestion, cross-file symbol resolution, and file-aware diagram navigation.
- Go and Java extractors. Their grammars are present, but unsupported extraction now returns an explicit error instead of silently using the Python extractor.
- More precise resolution for ambiguous object methods, nested functions, destructuring, dynamic imports, and inferred return shapes. Diagrams represent static relationships rather than a guaranteed runtime execution order.
- Broader documentation audits for nested return keys, tuple elements, and exceptions; the current gate checks the target, syntax, unchanged executable tokens, parameter/default documentation, returns sections, and prerequisite count.
- Repairing test harness failures after execution. Currently invalid syntax gets one generation retry, while actual runtime failures are reported without changing submitted source. Unexported JavaScript functions and unavailable internal imports may require additional harness support.
- Persistent sessions, authentication, concurrency controls, smaller editor/layout bundles, and a separate execution service before deployment beyond a trusted local machine.

See `GEMINI.md` for architectural invariants and `.agent/` for the original workflow instructions.

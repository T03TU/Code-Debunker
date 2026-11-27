# CodeDebunker

A local code exploration workbench. Paste or upload Python, JavaScript, or TypeScript to inspect functions, variables, imports, class relationships, and data flow. Click diagram elements to highlight their source in Monaco. Generate explanations, simulate test cases for a function or the full source flow, save the results, and run generated tests in Docker.

Structural analysis uses Tree-sitter and NetworkX; it needs neither an API key nor Docker and never executes submitted source.

## Open the app (Linux desktop)

Open **CodeDebunker** from the Applications menu. It starts the local app and opens your browser automatically, without a terminal. You can also double-click `CodeDebunker.desktop` in this project; GNOME may require **Allow Launching** for a file-manager shortcut the first time.

The launcher automatically creates the Python environment, installs dependencies, and builds the interface when necessary. A small progress window appears during setup. Later launches reuse the existing server and open the app immediately. It serves the built interface and API on one local port; Vite is not needed for normal use. If port 8000 is occupied, it selects another available local port automatically.

For a fresh checkout, register the desktop shortcut once:

```bash
python3 scripts/install_desktop.py
```

Or launch directly without registering a shortcut:

```bash
./CodeDebunker
```

Python 3.11+ is required. Node.js 20+ and npm are needed only when the interface needs to be built. Dependency downloads need an internet connection on first setup. An API key and Docker are optional for opening the app and exploring code structure.

The server stays in the background when you close the browser, so reopening is fast. Reopening checks whether the backend source has changed and restarts an outdated managed server before opening the interface. After an update restarts the backend, analyze your source again; saved library items remain available. Right-click the Applications-menu entry and choose **Stop CodeDebunker** to stop it. Terminal equivalents are:

```bash
./CodeDebunker --status
./CodeDebunker --stop
./CodeDebunker --no-browser  # Start without opening a browser or progress window.
```

Startup logs are in `.runtime/launcher.log`. Launcher state and control credentials are private to your user. The launcher checks an instance-specific token before reusing or stopping a server; it does not kill a process just because it occupies port 8000. If startup fails, the launcher displays an error with the log location. After correcting the problem, open it again to retry setup. Re-run `install_desktop.py` if you move the project folder.

## Developer startup

For frontend hot reload, the existing development workflow is still available. Install dependencies if necessary:

```bash
python3 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix frontend ci
```

Then run:

```bash
./CodeDebunker --stop
./scripts/dev.sh
```

Open **http://127.0.0.1:5173**. The frontend proxies `/api` requests to the backend on port 8000. API documentation is at **http://127.0.0.1:8000/docs**. Stop both development services with Ctrl+C. The developer script uses polling to handle systems with exhausted file watchers.

Open **Settings** using the gear button in the header. **Appearance** offers dark, light, or system color themes, five accent colors, text styles and sizes, and fine, regular, or bold icons. Changes apply immediately throughout the workspace, including the source editor and diagrams, and persist in this browser. **Reset appearance** restores the original theme.

## Explanations and generated tests

Open **Settings → LLM configuration** in the header to connect a model. The dialog opens automatically when no connection is configured; dismiss it to continue structural analysis. Choose a provider, enter the exact model ID (or Azure deployment name), and supply its credentials and endpoint where needed. **Test connection** makes a small request to check authentication and structured output; it may use provider credits. **Save settings** applies the configuration immediately, without restarting the app.

The dialog includes OpenAI, Anthropic, Google Gemini, Azure OpenAI, Amazon Bedrock, Google Cloud Vertex AI, OpenRouter, Ollama, and LM Studio. **Other OpenAI-compatible service** supports endpoints such as vLLM, llama.cpp, and private gateways. **Other provider (LiteLLM)** accepts `provider/model` identifiers for additional [LiteLLM-supported providers](https://docs.litellm.ai/docs/providers). Model names are editable rather than restricted to a fixed catalog. The model must support tool calling or JSON output; choose the appropriate **Structured output** mode and test it.

For local models, start your model server and load or install the model first. Ollama defaults to `http://127.0.0.1:11434` (server root, without `/v1`); LM Studio defaults to `http://127.0.0.1:1234/v1`. No API key is required for an unauthenticated local server. Addresses are resolved from the backend machine; when the backend runs in a container or on another machine, enter an address it can reach.

For Ollama, **JSON mode** sends the response schema directly to the server. Structured requests disable thinking output where supported (GPT-OSS uses its lowest reasoning level) so the model can return the requested result within its output budget. Local connection checks allow up to 90 seconds for model loading and CPU inference, and report a timeout separately from other connection failures.

Full explanations and test suites are larger than a connection check. Ollama and LM Studio generation requests allow up to ten minutes each, and explanations finish before test generation starts so the two jobs do not compete for one local model. Validated explanations appear as soon as they are ready. If tests fail afterward, the explanation remains available. Generation errors distinguish a timeout, a lost connection, invalid structured output, and a failed annotation or test validation.

Azure requires its resource endpoint and API version. Bedrock accepts an API key or AWS access key, secret, optional session token, and region. Vertex accepts project, location, and service account JSON. Bedrock and Vertex can also use an existing backend cloud identity when explicit credentials are omitted. Provider-side account access and model permissions are still required.

Settings are saved in `.runtime/llm-settings.json`, a file readable and writable only by your OS user (mode `0600`), excluded from source control. Credentials are stored locally in this file as plain text, never returned by the settings API or saved in browser storage. Leaving a credential field blank keeps its saved value for the same service. Changing provider, endpoint, or cloud account requires entering credentials again. Use **Forget existing credentials** to remove saved values while saving replacements or an anonymous local connection. Configuration changes separate the generation cache, so later requests use the selected model.

Existing `OPENAI_API_KEY`, `OPENAI_MODEL` (default `gpt-4o`), and optional `OPENAI_BASE_URL` environment variables remain supported until settings are saved through the dialog. The desktop launcher and developer script load `backend/.env`; manual Uvicorn startup can use `--env-file .env`. Saved dialog settings take precedence. Deleting `.runtime/llm-settings.json` restores environment-based defaults.

**Explain function** sends the selected callable's source and immediate dependency context to the configured model. It generates language identification, a Feynman explanation, annotated code, an illustrative execution walkthrough, prerequisite concepts, and tests. It never sends the entire source file to the model. Structural validation runs before each generated artifact is emitted; one corrective retry receives the validation errors. The annotated target must preserve its executable tokens. These checks do not prove semantic correctness; use the actual test results to evaluate behavior.

In **Tests & simulation**, choose **Selected function** or **Full source flow**, then select **Generate test cases**. This works independently of explanation generation and requires only your connected model. Each case shows concrete inputs, expected and model-predicted outcomes, intermediate steps, and a rationale. The suite describes the code's purpose and includes runnable pytest or Jest tests. Model predictions are illustrative and do not establish whether the tests pass.

Explanations, test generation, and Docker simulations continue when you select another function or variable. Each function keeps its own progress, results, and errors; select it again to return to its work. The running-work links above the workspace also return you to an active job. Full source flow results are independent of the selected function. Editing or replacing source, analyzing again, or saving a new model configuration clears this work so old results cannot appear under a new analysis. Use the saved library to keep completed results beyond the current analysis.

Function mode uses the selected callable and its immediate context. Full source flow sends the **complete submitted file**, call relationships, dependencies, and data transformations to your configured model to cover entry points and helper chains. It also supports module-level code without callable definitions. Available explanations from the same model configuration supply additional context, checked against the source. Function suites and full-flow suites have separate caches. **Run tests in Docker** executes the generated suite for the chosen scope and displays actual execution results separately from predictions. Full-flow results describe the suite as a whole; they do not mark an individual function as passing.

Use **Save explanation** or **Save test cases** to keep an item in **Saved library**. The browser stores a source snapshot, filename, target, scope, explanation or scenarios and runnable test code, plus any execution report available when saving. Each new item records the model and provider that generated it, captured by the backend for that request. The library and downloads include this attribution even if the configured model later changes; older items display **Model: Not recorded**. Saved entries survive page reloads, source edits, and backend session expiration. Open the library to preview, download, or remove them. Storage belongs to this browser and application origin; clearing browser data or changing the host/port changes access to the library. LLM connection credentials are not part of saved items.

Downloads are available without saving to the library: explanations as Markdown, test cases and their source snapshot as JSON, and runnable test code as `.py`, `.test.js`, or `.test.ts`. Downloaded tests import `source_target`; save the corresponding original source beside them as `source_target.py`, `source_target.js`, or `source_target.ts` when using your own test environment. Within the app, execution continues to use the isolated Docker runner.

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
# Launcher tests, from the project root
backend/.venv/bin/python -m pytest scripts/tests -q

# Include real launcher lifecycle checks (starts/stops the local app)
RUN_LAUNCHER_TESTS=1 backend/.venv/bin/python -m pytest scripts/tests -q

cd backend
.venv/bin/python -m pytest -q

# Include real isolated execution tests; requires the image above.
RUN_SANDBOX_TESTS=1 .venv/bin/python -m pytest -q

cd ../frontend
npm run build
node --test tests/api-routing.test.mjs
```

Simulation and saved-library verification: **102 backend tests passed** (five optional Docker integration checks skipped), and the production build passed. Headless Chrome checks covered function and full-flow predictions, saved explanations and test cases, reload persistence, downloads, source invalidation, and mobile layout. Model responses and Docker reports were mocked for these workflow checks; no live provider generation was performed.

The navigation regression in `frontend/tests/background-learning.mjs` verifies ongoing work across function and variable selection, concurrent explanations, full-flow results, target-specific failures, and cancellation after source replacement. It uses mocked model and Docker responses through real HTTP connections. To run from the repository root, use an installed Playwright module and Chromium browser:

```bash
CODEDEBUNKER_PLAYWRIGHT=/absolute/path/to/playwright/index.mjs \
CODEDEBUNKER_CHROME=/absolute/path/to/chrome \
node frontend/tests/background-learning.mjs
```

Desktop-launcher verification: **82 combined tests passed**, including 24 launcher unit checks, three real startup/lifecycle checks, and the 55 backend/sandbox checks. The installed desktop entry also passes `desktop-file-validate`.

Workbench verification: **55 tests passed with real Docker execution enabled**, the TypeScript/Vite production build passed, and Chrome checks covered all three languages, function selection, diagrams, source invalidation, and mobile layout. Desktop and mobile captures are in `artifacts/`.

Local Ollama verification: **96 backend tests passed** (five optional sandbox checks skipped). A real Chrome run with `qwen3.5:4b` completed the built-in Python example: all five explanation sections and a four-test suite passed structural validation. This CPU run took about 13 minutes including correction passes; the generated tests were not executed as part of that check. Cloud model generation has not been exercised.

Default tests mock model and Docker calls. Opt-in tests exercise real Python, JavaScript, and TypeScript runners, assertion failures, timeout cleanup, non-root execution, and read-only source mounts. Submitted source and generated tests execute only in Docker.

## Serve the production build locally

```bash
npm --prefix frontend run build
cd backend
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Build before starting the backend. FastAPI serves `frontend/dist` at **http://127.0.0.1:8000** when it exists. Monaco and its workers are bundled locally.

## Project state and remaining work

The Antigravity handoff contained a working parser/model foundation and eight passing tests, API and sandbox scaffolding, and an incomplete frontend with a missing `App` component. The continued implementation adds the workbench and closes critical API, graph, validation, and sandbox integration gaps.

The current milestone supports **single source files and snippets**, up to 200 KB. It is a local workbench, with in-memory sessions that expire after an hour and a 100-session limit. Sessions disappear when the backend restarts; use one backend worker. It has no authentication and is not prepared for public deployment.

Further planned work:

- Multi-file and repository ingestion, cross-file symbol resolution, and file-aware diagram navigation.
- Go and Java extractors. Their grammars are present, but unsupported extraction now returns an explicit error instead of silently using the Python extractor.
- More precise resolution for ambiguous object methods, nested functions, destructuring, dynamic imports, and inferred return shapes. Diagrams represent static relationships rather than a guaranteed runtime execution order.
- Broader documentation audits for nested return keys, tuple elements, and exceptions; the current gate checks the target, syntax, unchanged executable tokens, parameter/default documentation, returns sections, and prerequisite count.
- Repairing test harness failures after execution. Currently invalid syntax gets one generation retry, while actual runtime failures are reported without changing submitted source. Unexported JavaScript functions and unavailable internal imports may require additional harness support.
- Persistent sessions, authentication, concurrency controls, smaller editor/layout bundles, and a separate execution service before deployment beyond a trusted local machine.

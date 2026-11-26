// From the repository root, run node frontend/tests/background-learning.mjs.
// Set CODEDEBUNKER_PLAYWRIGHT to an installed Playwright module path if needed.
// Set CODEDEBUNKER_CHROME to a browser executable to use instead of Playwright's Chromium.
import assert from "node:assert/strict";
import { once } from "node:events";
import { createServer } from "node:http";
import { setTimeout as delay } from "node:timers/promises";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const { chromium } = await import(process.env.CODEDEBUNKER_PLAYWRIGHT || "playwright");
const frontend = fileURLToPath(new URL("..", import.meta.url));
const bundle = await build({
  absWorkingDir: frontend,
  entryPoints: ["src/main.tsx"],
  outfile: "/tmp/codedebunker-background-learning.js",
  bundle: true,
  write: false,
  format: "esm",
  define: { "process.env.NODE_ENV": '"production"' },
  plugins: [{
    name: "editor-and-diagram-stubs",
    setup(plugin) {
      // Keep the app and its workspace handlers intact without compiling Monaco or ELK.
      plugin.onResolve({ filter: /^@\/components\/(CodeEditor|Diagram)$/ }, ({ path }) => ({
        path,
        namespace: "browser-test-stub",
      }));
      plugin.onLoad({ filter: /.*/, namespace: "browser-test-stub" }, ({ path }) => ({
        contents: path.endsWith("/CodeEditor")
          ? 'import { createElement } from "react"; export default function Editor({ span }) { return createElement("output", { "aria-label": "Highlighted line" }, span?.start_line); }'
          : 'export default function Diagram() { return null; }',
        resolveDir: frontend,
      }));
    },
  }],
});

const analysisId = "analysis-browser-test";
const functions = ["checkout", "main"].map((name, index) => ({
  id: name,
  name,
  qualname: name,
  parameters: [],
  span: { start_line: index + 1, end_line: index + 1, start_col: 0, end_col: 6 },
}));
const diagram = { view: "class", nodes: [], edges: [] };
const variable = {
  id: "total",
  name: "total",
  scope: "local",
  span: { start_line: 3, end_line: 3, start_col: 0, end_col: 5 },
};
const analysis = {
  analysis_id: analysisId,
  entry_point_symbol_id: "checkout",
  class_diagram: diagram,
  dataflow_diagram: diagram,
  ir: {
    metadata: { primary_language: "python", diagnostics: [] },
    symbols: { callables: functions, variables: [variable] },
    dependencies: [],
  },
};
function suiteFor(target, purpose = `Test cases for ${target}`) {
  return {
    language: "python",
    framework: "pytest",
    purpose,
    mock_summary: "No external dependencies.",
    test_code: "def test_example(): assert True",
    test_case_names: ["test_example"],
    scenarios: [{
      name: "test_example",
      category: "happy_path",
      input: "[]",
      expected_output: "0",
      predicted_output: "0",
      steps: ["Calculate the total."],
      rationale: "Example.",
    }],
  };
}

const pending = new Map();
function nextJob(kind) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`No ${kind} request arrived`)), 10_000);
    pending.set(kind, job => {
      clearTimeout(timer);
      resolve(job);
    });
  });
}
function hold(kind, target, response, finish) {
  const accept = pending.get(kind);
  assert(accept, `Unexpected ${kind} request`);
  pending.delete(kind);
  const closed = once(response, "close");
  const waitForClose = () => Promise.race([
    closed,
    delay(8_000, undefined, { ref: false }).then(() => {
      throw new Error(`Timed out waiting for ${kind} to close`);
    }),
  ]);
  accept({
    target,
    waitForClose,
    get disconnected() { return response.destroyed && !response.writableEnded; },
    async finish() {
      assert(!this.disconnected, `${kind} lost its connection after changing selection`);
      finish();
      await waitForClose();
      assert(response.writableEnded);
    },
    async fail(detail) {
      assert(!this.disconnected, `${kind} lost its connection before failure`);
      json(response, { detail }, 502);
      await waitForClose();
    },
  });
}
function json(response, data, status = 200) {
  response.writeHead(status, { "Content-Type": "application/json" });
  response.end(JSON.stringify(data));
}
function event(response, type, data) {
  response.write(`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`);
}

const server = createServer(async (request, response) => {
  try {
    const url = new URL(request.url, "http://localhost");
    if (url.pathname === "/") {
      response.writeHead(200, { "Content-Type": "text/html" });
      response.end('<!doctype html><link rel="stylesheet" href="/app.css"><div id="root"></div><script type="module" src="/app.js"></script>');
    } else if (url.pathname === "/app.css" || url.pathname === "/app.js") {
      const isCss = url.pathname.endsWith(".css");
      response.writeHead(200, { "Content-Type": isCss ? "text/css" : "application/javascript" });
      response.end(bundle.outputFiles.find(file => file.path.endsWith(isCss ? ".css" : ".js")).contents);
    } else if (url.pathname === "/api/capabilities") {
      json(response, { languages: ["python"], llm_configured: true, sandbox_available: true });
    } else if (url.pathname === "/api/analyze") {
      json(response, analysis);
    } else if (url.pathname.startsWith("/api/slice/")) {
      json(response, {
        slice: { upstream_callables: [], downstream_callables: [], data_flows: [] },
        dataflow_diagram: diagram,
      });
    } else if (url.pathname.startsWith("/api/stream/")) {
      const target = url.searchParams.get("symbol_id");
      response.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" });
      event(response, "slice_ready", { target_symbol_id: target, target_name: target });
      hold("explanation", target, response, () => {
        event(response, "section", { name: "feynman_explanation", content: `Explanation for ${target}` });
        event(response, "tests", suiteFor(target, `Test cases with explanation for ${target}`));
        event(response, "qa_result", { passed: true, errors: [] });
        event(response, "done", {});
        response.end();
      });
    } else if (url.pathname.startsWith("/api/tests/") || url.pathname.startsWith("/api/simulate/")) {
      let body = "";
      for await (const chunk of request) body += chunk;
      const { scope, target_symbol_id } = JSON.parse(body);
      const target = target_symbol_id ?? scope;
      const suite = suiteFor(target);
      if (url.pathname.startsWith("/api/tests/")) {
        hold("test generation", target, response, () => json(response, {
          analysis_id: analysisId,
          target_symbol_id,
          scope,
          suite,
        }));
      } else {
        hold("test execution", target, response, () => json(response, {
          analysis_id: analysisId,
          target_symbol_id,
          scope,
          test_code: suite.test_code,
          execution: {
            status: "PASS",
            exit_code: 0,
            tests: [{
              nodeid: "test_example",
              name: "test_example",
              outcome: "passed",
              duration: 0.001,
              message: null,
            }],
            stdout: "",
            stderr: "",
            duration_seconds: 0.01,
          },
        }));
      }
    } else {
      response.writeHead(404);
      response.end();
    }
  } catch (error) {
    console.error(error);
    response.destroy();
  }
});

server.listen(0, "127.0.0.1");
await once(server, "listening");
let browser;
try {
  browser = await chromium.launch({
    executablePath: process.env.CODEDEBUNKER_CHROME || undefined,
    headless: true,
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(8_000);
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  const tab = name => page.getByRole("tab", { name });
  const button = name => page.getByRole("button", { name, exact: true });
  const chooseFunction = name => page.getByLabel("Selected function").selectOption(name);
  const currentFunction = () => page.getByLabel("Selected function").inputValue();
  const output = value => page.getByText(value, { exact: true });
  const testsTab = /Tests & simulation/;
  await button("Analyze source").click();
  await chooseFunction("checkout");

  // Leave A's explanation pending while inspecting B and a variable.
  await tab("Explanation").click();
  const explaining = nextJob("explanation");
  await button("Explain function").click();
  const explanation = await explaining;
  assert.equal(explanation.target, "checkout");
  await tab("Structure").click();
  await chooseFunction("main");
  await tab(/variables/i).click();
  await page.getByRole("button", { name: /total/ }).click();
  await page.getByLabel("Highlighted line").getByText("3").waitFor();
  assert.equal(await currentFunction(), "main");
  await tab("Explanation").click();
  assert(await button("Explain function").isVisible());
  await button("Explanation · checkout").click();
  assert.equal(await currentFunction(), "checkout");
  const explainingButton = button("Explaining…");
  await explainingButton.waitFor();
  assert(await explainingButton.isDisabled());
  await chooseFunction("main");
  const explainingMain = nextJob("explanation");
  await button("Explain function").click();
  const mainExplanation = await explainingMain;
  assert.equal(mainExplanation.target, "main");
  await mainExplanation.finish();
  await output("Explanation for main").waitFor();
  await explanation.finish();
  assert.equal(await currentFunction(), "main");
  assert.equal(await output("Explanation for checkout").count(), 0);
  await chooseFunction("checkout");
  await output("Explanation for checkout").waitFor();

  // A's independently generated tests should also finish while B is selected.
  await tab(testsTab).click();
  const generating = nextJob("test generation");
  await button("Generate test cases").click();
  const tests = await generating;
  assert.equal(tests.target, "checkout");
  await chooseFunction("main");
  await tab("Structure").click();
  await tests.finish();
  assert.equal(await tab("Structure").getAttribute("aria-selected"), "true");
  await tab(testsTab).click();
  assert.equal(await output("Test cases for checkout").count(), 0);
  await chooseFunction("checkout");
  await output("Test cases for checkout").waitFor();

  // Docker results belong to their original target even after selection changes.
  const executing = nextJob("test execution");
  await button("Run tests in Docker").click();
  const execution = await executing;
  assert.equal(execution.target, "checkout");
  await chooseFunction("main");
  await execution.finish();
  assert.equal(await page.getByText(/Actual Docker execution/).count(), 0);
  await chooseFunction("checkout");
  await page.getByText(/Actual Docker execution/).waitFor();

  // Whole-flow suites are independent of the selected function and variable.
  const testScope = page.getByLabel("Test scope");
  await testScope.selectOption("flow");
  const generatingFlow = nextJob("test generation");
  await button("Generate test cases").click();
  const flow = await generatingFlow;
  assert.equal(flow.target, "flow");
  await testScope.selectOption("function");
  await chooseFunction("main");
  await page.getByRole("button", { name: /total/ }).click();
  await button("Test generation · Full source flow").click();
  assert.equal(await testScope.inputValue(), "flow");
  assert.equal(await currentFunction(), "main");
  await flow.finish();
  await output("Test cases for flow").waitFor();
  await chooseFunction("checkout");
  await output("Test cases for flow").waitFor();

  const executingFlow = nextJob("test execution");
  await button("Run tests in Docker").click();
  const flowExecution = await executingFlow;
  assert.equal(flowExecution.target, "flow");
  await chooseFunction("main");
  await flowExecution.finish();
  await page.getByText(/Actual Docker execution/).waitFor();
  await testScope.selectOption("function");
  assert.equal(await page.getByText(/Actual Docker execution/).count(), 0);

  // A failed request should surface only for the target that started it.
  await chooseFunction("checkout");
  const failing = nextJob("test generation");
  await button("Generate test cases").click();
  const failed = await failing;
  await chooseFunction("main");
  const failure = "The model could not create checkout tests.";
  await failed.fail(failure);
  assert.equal(await output(failure).count(), 0);
  await chooseFunction("checkout");
  await output(failure).waitFor();
  await chooseFunction("main");
  assert.equal(await output(failure).count(), 0);

  // Replacing the source clears stale learning results.
  await testScope.selectOption("flow");
  const generatingAfterEdit = nextJob("test generation");
  await button("Generate test cases").click();
  const oldSource = await generatingAfterEdit;
  await page.getByLabel("Load example").selectOption("javascript");
  await oldSource.waitForClose();
  assert(oldSource.disconnected);
  assert.equal(await output("Test cases for flow").count(), 0);
  await tab("Explanation").click();
  assert.equal(await output("Explanation for checkout").count(), 0);
  assert.deepEqual(errors, []);
  console.log("Background explanation, test generation, Docker execution, and full-flow tests passed.");
} finally {
  await browser?.close();
  server.closeAllConnections();
  await new Promise(resolve => server.close(resolve));
}

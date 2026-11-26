import assert from "node:assert/strict";
import { afterEach, mock, test } from "node:test";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";

const bundle = await build({
  entryPoints: [fileURLToPath(new URL("../src/lib/api.ts", import.meta.url))],
  bundle: true,
  platform: "node",
  format: "esm",
  write: false,
});
const { generateTestCases } = await import(
  `data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].contents).toString("base64")}`
);
afterEach(() => mock.restoreAll());

test("old backend reports how to load test generation instead of Method Not Allowed", async () => {
  mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "/api/tests/example");
    assert.equal(options.method, "POST");
    return new Response('{"detail":"Method Not Allowed"}', { status: 405 });
  });
  await assert.rejects(generateTestCases("example", "checkout", "function"), /Close and reopen CodeDebunker/);
});

test("expired analysis keeps the actionable backend error", async () => {
  mock.method(globalThis, "fetch", async () => new Response(
    '{"detail":"Analysis not found or expired. Analyze your source again."}', { status: 404 },
  ));
  await assert.rejects(generateTestCases("expired", "checkout", "function"), /Analyze your source again/);
});

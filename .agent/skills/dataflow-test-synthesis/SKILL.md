---
name: dataflow-test-synthesis
description: Synthesizes runnable pytest or Jest unit tests from JSON IR parameter shapes, dependency lists, and data-flow edges, then executes them in an isolated Docker sandbox.
---

# Data-Flow Unit Test & Sandbox Simulation Skill

## Instructions
1. Inspect `parameters`, `returns`, `dependencies`, and `edges.data_flows` in the 1-hop IR slice.
2. Generate a self-contained test suite (`pytest` for Python, `Jest` for TypeScript/JavaScript):
   - Stub/mock all `third_party` and `unresolved` entries in `ir.dependencies`.
   - Write a **happy-path test** matching `inferred_shape` that asserts intermediate transformations and final return values.
   - Write **boundary/falsy tests** (`None`/`null`, empty collections, malformed inputs).
3. Run the suite inside an isolated container (`--network none`, `--read-only`, 10s timeout) via the `sandbox-qa-gating` skill.
4. If the test fails due to a mock or import error in the generated test harness, repair the test and retry (max 2 attempts). Never modify the user's source code.
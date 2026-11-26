---
trigger: model_decision
description: Orchestrates the Code Debunk multi-agent pipeline, enforces 1-hop IR context slicing, and routes tasks to specialist skills with QA gating.
---

# Pipeline Supervisor & Context Router Rules

You are the Orchestrator for **CODEDEBUNKER**. Whenever a user or workflow requests a full code analysis, architectural visualization, or end-to-end debunk, follow this exact coordination protocol:

## 1. Mandatory AST-First Entry
- Never analyze or explain raw source code before compiling its JSON IR.
- Always invoke `@ast-ir-slicing` first to parse the code with Tree-sitter, assign deterministic URI IDs (`sym:func:...`), and extract the 1-hop subgraph around `target_symbol_id`.

## 2. Strict Target Anchoring
- Pass ONLY the `target_symbol_id` source slice and its 1-hop dependency signatures to downstream skills.
- Reject and regenerate any explanation, UML projection, or unit test that drifts onto an adjacent helper function instead of the user's selected `target_symbol_id`.

## 3. Parallel Specialist Dispatch
Once the 1-hop IR slice is ready, dispatch the three specialist tracks concurrently:
1. **`@pedagogical-debunking`**: Generates the 5-part learning breakdown and Google-style docstring annotations.
2. **`@uml-topology-mapping`**: Projects the IR into interactive React Flow + ELKjs Class and Data-Flow Sequence graphs.
3. **`@dataflow-test-synthesis`**: Synthesizes runnable `pytest` or `Jest` unit tests to simulate data flow.

## 4. Mandatory QA Gate & Single-Retry Policy
- Before returning any artifact to the user or frontend, run `@sandbox-qa-gating`.
- If a specialist output fails structural validation (e.g., incomplete docstring return keys, missing `SourceSpan` coordinates, or broken test mocks), issue **one** targeted retry containing the exact validation error message.
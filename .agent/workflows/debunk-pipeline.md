---
description: Run the end-to-end Code Debunk pipeline (AST IR extraction -> Parallel Debunk, UML Spec, and Sandboxed Unit Tests -> QA Gate).
---

# End-to-End Code Debunk Workflow

Execute the following stages in order for the active file or selected function:

1. **Deterministic IR Extraction:**
   Invoke `@ast-ir-slicing` to parse the target code with Tree-sitter and output the 1-hop JSON IR slice.
2. **Parallel Specialist Execution:**
   Using the JSON IR slice from Step 1, execute these three tasks in parallel:
   - Run `@pedagogical-debunking` to generate the 5-part explanation and Google-style docstring annotations.
   - Run `@uml-topology-mapping` to produce the React Flow + ELKjs UML JSON graph.
   - Run `@dataflow-test-synthesis` to generate unit tests and execute them in the Docker sandbox.
3. **Final QA Gate:**
   Verify that:
   - All five sections of `@pedagogical-debunking` are present and the docstring documents every parameter and return key.
   - Every UML node and edge retains valid `span` line numbers.
   - Unit test `PASS`/`FAIL` badges are mapped to the corresponding IR `symbol_id`s.
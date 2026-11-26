# CODEDEBUNKER — Project Architecture & Engineering Invariants

## Project Overview
**CODEDEBUNKER** is a full-stack code reverse-engineering, visualization, and simulation platform. Users submit arbitrary source code (snippets, files, or repositories) to inspect variables, functions, and dependencies, explore interactive UML Class and Data-Flow Sequence diagrams, read structured pedagogical explanations, and run auto-generated unit tests that simulate data flow.

## Monorepo Layout
- `backend/`: Python 3.11+, FastAPI, Pydantic v2, `tree-sitter` (multi-language grammars), `networkx`, `instructor`, and `docker` SDK.
- `frontend/`: React 18, TypeScript, Vite, `@xyflow/react` (React Flow), `elkjs`, `@monaco-editor/react`, and Tailwind CSS.
- `.agent/`: Workspace rules, workflows, and modular skills for Antigravity agents.

## Core Architectural Invariants
1. **Deterministic Structure, Probabilistic Semantics:**
   - Never use regular expressions or LLMs to extract variables, functions, imports, or line numbers. All structural extraction must compile through **Tree-sitter** into our normalized flat property-graph **JSON Intermediate Representation (IR)**.
   - Use LLMs strictly for semantic tasks grounded in the IR: Feynman analogies, docstrings, inline annotations, dynamic shape inference, and unit test synthesis.
2. **Exact Source Span Grounding:**
   - Every symbol, dependency, and edge in the JSON IR must preserve exact `SourceSpan` coordinates (`start_line`, `end_line`, `start_col`, `end_col`) so clicking any UML node or edge highlights the corresponding lines in Monaco Editor.
3. **1-Hop Dependency Graph Slicing:**
   - Never send entire repositories to an LLM. Slice only the target callable, its immediate 1-hop upstream/downstream dependencies, and its `data_flows` edges via `NetworkX`.
4. **Pedagogical Output Standard:**
   - Every code debunk response must contain all five sections: (1) Language Identification, (2) Feynman Explanation, (3) Annotated Code with an exhaustive Google-style docstring (documenting every argument, optional default, dictionary key, and tuple return element) plus step-by-step inline comments, (4) Simulated Execution Walkthrough, and (5) Prerequisite Concepts.
5. **Zero-Trust Execution:**
   - Untrusted user code and generated unit tests must execute exclusively inside ephemeral, network-disabled Docker containers—never on the host OS.
---
name: ast-ir-slicing
description: Deterministically parses source code with Tree-sitter, compiles a normalized JSON Intermediate Representation (IR), and extracts 1-hop dependency subgraphs. Use whenever analyzing code structure, variables, functions, imports, or line spans.
---

# AST & JSON IR Slicing Skill

## Instructions
1. NEVER parse source code manually or guess variable/function line numbers.
2. Execute the deterministic IR extractor script against the target file:
   ```bash
   python .agent/skills/ast-ir-slicing/scripts/slice_ir.py --file <target_file> --symbol <target_symbol_id> --hops 1
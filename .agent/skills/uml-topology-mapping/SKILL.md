---
name: uml-topology-mapping
description: Projects the normalized JSON IR into interactive React Flow and ELKjs UML Class/Component diagrams and Data-Flow Sequence pipelines with click-to-code span mapping.
---

# UML & Data-Flow Topology Skill

## Instructions
1. Read the compiled JSON IR (`symbols`, `dependencies`, and `edges`).
2. Infer missing structural shapes (`inferred_shape`) for dynamically typed variables where `declared_type` is `null`.
3. Generate two diagram projections:
   - **Class & Component View:** Map `symbols.containers` with their `field` variables and `method` callables; connect `dependencies` as external boundary nodes.
   - **Sequence & Data-Flow Pipeline View:** Order `edges.calls` and `edges.data_flows` by `sequence_order` and `step` with concise action labels (max 6 words).
4. Preserve exact `span` coordinates on every node and edge so clicking any UML element highlights the corresponding lines in Monaco Editor.
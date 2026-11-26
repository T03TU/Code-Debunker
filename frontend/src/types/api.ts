// API types mirroring the backend Pydantic models

export interface SourceSpan {
  start_line: number;
  end_line: number;
  start_col: number;
  end_col: number;
}

export interface ParameterInfo {
  id: string;
  name: string;
  declared_type: string | null;
  inferred_shape: string | null;
  default_value: string | null;
  is_optional: boolean;
  span: SourceSpan;
}

export interface CallableNode {
  id: string;
  name: string;
  qualname: string;
  kind: "function" | "method" | "closure" | "constructor";
  parameters: ParameterInfo[];
  return_type: string | null;
  inferred_return_shape: string | null;
  purity: "pure" | "impure" | "unknown";
  is_async: boolean;
  container_id: string | null;
  module_id: string;
  span: SourceSpan;
  source_excerpt: string;
}

export interface ContainerNode {
  id: string;
  name: string;
  kind: "class" | "struct" | "interface" | "enum";
  bases: string[];
  field_ids: string[];
  method_ids: string[];
  module_id: string;
  span: SourceSpan;
}

export interface VariableNode {
  id: string;
  name: string;
  scope: "global" | "field" | "parameter" | "local";
  mutability: "mutable" | "immutable" | "unknown";
  declared_type: string | null;
  inferred_shape: string | null;
  default_value: string | null;
  is_optional: boolean;
  owner_id: string | null;
  module_id: string;
  span: SourceSpan;
}

export interface DependencyNode {
  id: string;
  name: string;
  alias: string | null;
  imported_symbols: string[];
  category: "stdlib" | "third_party" | "internal_module" | "unresolved";
  module_id: string;
  span: SourceSpan;
}

export interface CallEdge {
  id: string;
  source_id: string;
  target_id: string;
  target_name: string;
  sequence_order: number;
  arguments: string[];
  span: SourceSpan;
}

export interface DataFlowEdge {
  id: string;
  source_id: string;
  target_id: string;
  variable_name: string;
  step: number;
  transformation_summary: string;
  span: SourceSpan;
}

export interface TypeRelationEdge {
  id: string;
  source_id: string;
  target_id: string;
  target_name: string;
  relation: "inherits" | "implements" | "composes";
  span: SourceSpan;
}

export interface IRMetadata {
  primary_language: string;
  runtime_paradigm: string;
  entry_points: string[];
  topological_order: string[];
  diagnostics: Array<{ severity: string; message: string; span?: SourceSpan }>;
}

export interface ProgramIR {
  analysis_id: string;
  metadata: IRMetadata;
  modules: Array<{
    id: string;
    path: string;
    language: string;
    line_count: number;
    span: SourceSpan;
  }>;
  dependencies: DependencyNode[];
  symbols: {
    containers: ContainerNode[];
    callables: CallableNode[];
    variables: VariableNode[];
  };
  edges: {
    calls: CallEdge[];
    data_flows: DataFlowEdge[];
    type_relations: TypeRelationEdge[];
  };
}

export interface IRSlice {
  analysis_id: string;
  target_symbol_id: string;
  primary_language: string;
  runtime_paradigm: string;
  target_callable: CallableNode;
  upstream_callables: CallableNode[];
  downstream_callables: CallableNode[];
  related_containers: ContainerNode[];
  dependencies: DependencyNode[];
  variables: VariableNode[];
  calls: CallEdge[];
  data_flows: DataFlowEdge[];
  type_relations: TypeRelationEdge[];
}

// UML types
export interface UMLNodeData {
  label: string;
  kind: "callable" | "container" | "variable" | "dependency" | "external";
  span: SourceSpan | null;
  extra: Record<string, unknown>;
}

export interface UMLNode {
  id: string;
  type: "umlNode";
  position: { x: number; y: number };
  data: UMLNodeData;
  source_id: string;
}

export interface UMLEdgeData {
  label: string;
  kind: "call" | "data_flow" | "type_relation" | "dependency";
  span: SourceSpan | null;
  sequence_order?: number;
  step?: number;
}

export interface UMLEdge {
  id: string;
  source: string;
  target: string;
  animated: boolean;
  data: UMLEdgeData;
  source_edge_id: string;
}

export interface UMLDiagram {
  view: "class" | "dataflow";
  nodes: UMLNode[];
  edges: UMLEdge[];
  elk_options: Record<string, string>;
}

// API responses
export interface AnalyzeResponse {
  analysis_id: string;
  ir: ProgramIR;
  class_diagram: UMLDiagram;
  dataflow_diagram: UMLDiagram | null;
  entry_point_symbol_id: string | null;
}

export interface TestCaseResult {
  nodeid: string;
  name: string;
  outcome: "passed" | "failed" | "error" | "skipped";
  duration: number;
  message: string | null;
}

export interface SandboxExecutionResult {
  status: "PASS" | "FAIL" | "ERROR" | "TIMEOUT";
  exit_code: number;
  tests: TestCaseResult[];
  stdout: string;
  stderr: string;
  duration_seconds: number;
}

export interface SimulateResponse {
  analysis_id: string;
  target_symbol_id: string | null;
  scope: TestScope;
  test_code: string;
  execution: SandboxExecutionResult;
}

// App state
export interface PrerequisiteConcept {
  name: string;
  explanation: string;
}

export interface DebunkSections {
  language_identification: string;
  feynman_explanation: string;
  annotated_code: string;
  simulated_walkthrough: string;
  prerequisite_concepts: PrerequisiteConcept[];
}

export interface TestSuite {
  language: string;
  framework: string;
  test_code: string;
  mock_summary: string;
  test_case_names: string[];
  purpose: string;
  scenarios: SimulatedTestCase[];
}

export type TestScope = "function" | "flow";

export interface SimulatedTestCase {
  name: string;
  category: "happy_path" | "transformation" | "edge_case" | "boundary";
  input: string;
  expected_output: string;
  predicted_output: string;
  steps: string[];
  rationale: string;
}

export interface TestsResponse {
  analysis_id: string;
  target_symbol_id: string | null;
  scope: TestScope;
  suite: TestSuite;
}

export interface QAResult {
  passed: boolean;
  errors: string[];
}

// Span-based selection for Monaco <-> UML sync
export interface SpanSelection {
  symbolId: string;
  span: SourceSpan;
  source: "editor" | "uml";
}

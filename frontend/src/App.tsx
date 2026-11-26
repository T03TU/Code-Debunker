import {
  lazy,
  Suspense,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
} from "react";
import {
  Braces,
  Check,
  ChevronDown,
  CircleHelp,
  Code2,
  Download,
  FileCode2,
  GitBranch,
  Layers,
  LoaderCircle,
  Play,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Sparkles,
  Upload,
  X,
} from "lucide-react";
import {
  analyzeCode,
  getCapabilities,
  getSlice,
  simulate,
  streamDebunk,
  type Capabilities,
} from "@/lib/api";
import { samples } from "@/lib/samples";
import LLMSettingsDialog from "@/components/LLMSettingsDialog";
import type {
  AnalyzeResponse,
  DebunkSections,
  IRSlice,
  QAResult,
  SimulateResponse,
  SourceSpan,
  TestSuite,
  UMLDiagram,
} from "@/types/api";

const CodeEditor = lazy(() => import("@/components/CodeEditor"));
const Diagram = lazy(() => import("@/components/Diagram"));
type Tab = "structure" | "explanation" | "tests";
const sectionNames = {
  language_identification: "Language identification",
  feynman_explanation: "The everyday explanation",
  annotated_code: "Annotated code",
  simulated_walkthrough: "Execution walkthrough",
  prerequisite_concepts: "Concepts to know",
};
const message = (error: unknown) =>
  error instanceof Error ? error.message : "Something went wrong.";

export default function App() {
  const [code, setCode] = useState(samples.python.code);
  const [filename, setFilename] = useState(samples.python.filename);
  const [language, setLanguage] = useState("");
  const [analysis, setAnalysis] = useState<AnalyzeResponse | null>(null);
  const [selectedId, setSelectedId] = useState("");
  const [highlight, setHighlight] = useState<SourceSpan | null>(null);
  const [slice, setSlice] = useState<IRSlice | null>(null);
  const [flow, setFlow] = useState<UMLDiagram | null>(null);
  const [sliceLoading, setSliceLoading] = useState(false);
  const [tab, setTab] = useState<Tab>("structure");
  const [view, setView] = useState<"class" | "dataflow">("class");
  const [inventory, setInventory] = useState<
    "functions" | "variables" | "imports"
  >("functions");
  const [sections, setSections] = useState<Partial<DebunkSections>>({});
  const [suite, setSuite] = useState<TestSuite | null>(null);
  const [qa, setQa] = useState<QAResult | null>(null);
  const [execution, setExecution] = useState<SimulateResponse | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [simulating, setSimulating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null);
  const [apiOnline, setApiOnline] = useState<boolean | null>(null);
  const [help, setHelp] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const promptedForLLM = useRef(false);
  const upload = useRef<HTMLInputElement>(null);
  const stream = useRef<EventSource | null>(null);
  const sourceRevision = useRef(0);
  const jobRevision = useRef(0);

  async function refreshCapabilities() {
    try {
      const result = await getCapabilities();
      setCapabilities(result);
      setApiOnline(true);
      if (!promptedForLLM.current) {
        promptedForLLM.current = true;
        if (!result.llm_configured) setSettingsOpen(true);
      }
    } catch {
      setApiOnline(false);
      setCapabilities(null);
    }
  }
  useEffect(() => {
    void refreshCapabilities();
    return () => stream.current?.close();
  }, []);

  function resetLearning() {
    jobRevision.current++;
    stream.current?.close();
    stream.current = null;
    setGenerating(false);
    setSimulating(false);
    setSections({});
    setSuite(null);
    setQa(null);
    setExecution(null);
  }
  function invalidate() {
    sourceRevision.current++;
    resetLearning();
    setAnalysis(null);
    setSelectedId("");
    setHighlight(null);
    setSlice(null);
    setFlow(null);
    setError(null);
    setAnalyzing(false);
  }
  function editCode(value: string) {
    if (value !== code) {
      invalidate();
      setCode(value);
    }
  }
  function loadSample(key: keyof typeof samples) {
    invalidate();
    setCode(samples[key].code);
    setFilename(samples[key].filename);
    setLanguage(key);
  }
  function selectSymbol(id: string, span: SourceSpan | null) {
    if (span) setHighlight(span);
    if (
      id !== selectedId &&
      analysis?.ir.symbols.callables.some((item) => item.id === id)
    ) {
      resetLearning();
      setError(null);
      setSelectedId(id);
    }
  }
  const selected = analysis?.ir.symbols.callables.find(
    (item) => item.id === selectedId,
  );
  const editorLanguage =
    language ||
    analysis?.ir.metadata.primary_language ||
    (filename.endsWith(".ts")
      ? "typescript"
      : filename.endsWith(".js")
        ? "javascript"
        : "python");

  useEffect(() => {
    if (!analysis || !selectedId) {
      setSlice(null);
      setFlow(null);
      return;
    }
    let current = true;
    setSliceLoading(true);
    setFlow(null);
    setSlice(null);
    getSlice(analysis.analysis_id, selectedId)
      .then((result) => {
        if (current) {
          setSlice(result.slice);
          setFlow(result.dataflow_diagram);
        }
      })
      .catch((failure) => {
        if (current) setError(message(failure));
      })
      .finally(() => {
        if (current) setSliceLoading(false);
      });
    return () => {
      current = false;
    };
  }, [analysis, selectedId]);

  async function analyze() {
    if (analyzing || !code.trim()) return;
    resetLearning();
    setError(null);
    setAnalyzing(true);
    setTab("structure");
    const revision = ++sourceRevision.current;
    try {
      const result = await analyzeCode(
        code,
        filename || undefined,
        language || undefined,
      );
      if (revision !== sourceRevision.current) return;
      setAnalysis(result);
      setApiOnline(true);
      const id =
        result.entry_point_symbol_id ||
        result.ir.symbols.callables[0]?.id ||
        "";
      setSelectedId(id);
      setFlow(result.dataflow_diagram);
      setHighlight(
        result.ir.symbols.callables.find((item) => item.id === id)?.span ??
          null,
      );
      if (!capabilities) void refreshCapabilities();
    } catch (failure) {
      if (revision === sourceRevision.current) setError(message(failure));
    } finally {
      if (revision === sourceRevision.current) setAnalyzing(false);
    }
  }

  async function readFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (!/\.(py|js|ts|mjs|cjs)$/i.test(file.name)) {
      setError("Choose a Python, JavaScript, or TypeScript source file.");
      return;
    }
    if (file.size > 200_000) {
      setError("Choose a source file smaller than 200 KB.");
      return;
    }
    const revision = sourceRevision.current;
    try {
      const content = await file.text();
      if (sourceRevision.current !== revision) return;
      invalidate();
      setCode(content);
      setFilename(file.name);
      setLanguage("");
    } catch (failure) {
      setError(message(failure));
    }
  }

  function explain() {
    if (!analysis || !selected || generating) return;
    if (!capabilities?.llm_configured) {
      setSettingsOpen(true);
      return;
    }
    resetLearning();
    setGenerating(true);
    setError(null);
    setTab("explanation");
    const revision = jobRevision.current;
    stream.current = streamDebunk(
      analysis.analysis_id,
      selected.id,
      (event) => {
        if (revision !== jobRevision.current) return;
        if (event.type === "section" && event.name in sectionNames) {
          try {
            const value =
              event.name === "prerequisite_concepts"
                ? JSON.parse(event.content)
                : event.content;
            setSections((previous) => ({ ...previous, [event.name]: value }));
          } catch {
            setError(
              "The explanation contained an invalid section. Please retry.",
            );
          }
        } else if (event.type === "tests") setSuite(event);
        else if (event.type === "qa_result") setQa(event);
        else if (event.type === "error") setError(event.message);
      },
      () => {
        if (revision === jobRevision.current) setGenerating(false);
      },
    );
  }

  async function runSimulation() {
    if (!analysis || !selected || simulating) return;
    setSimulating(true);
    setError(null);
    setTab("tests");
    const revision = jobRevision.current;
    try {
      const result = await simulate(analysis.analysis_id, selected.id);
      if (revision === jobRevision.current) setExecution(result);
    } catch (failure) {
      if (revision === jobRevision.current) setError(message(failure));
    } finally {
      if (revision === jobRevision.current) setSimulating(false);
    }
  }

  function exportIR() {
    if (!analysis) return;
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(analysis.ir, null, 2)], {
        type: "application/json",
      }),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${filename || "analysis"}.ir.json`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const aiReady = Boolean(capabilities?.llm_configured);
  const sandboxReady = Boolean(capabilities?.sandbox_available);
  const diagram = view === "class" ? analysis?.class_diagram : flow;
  const busy = generating || simulating;
  const testCode = execution?.test_code || suite?.test_code;

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/" aria-label="CodeDebunker home">
          <span className="brand-icon">
            <Braces size={24} />
          </span>
          <span>
            code<span className="brand-light">debunker</span>
            <small>SEE HOW CODE WORKS</small>
          </span>
        </a>
        <div className="header-center">
          <span className="workspace-pill">LOCAL WORKSPACE</span>
          <span className="header-caption">
            Read it. Trace it. Understand it.
          </span>
        </div>
        <button
          className="button settings-trigger"
          onClick={() => setSettingsOpen(true)}
          aria-haspopup="dialog"
        >
          <Settings2 size={17} /> LLM settings
        </button>
        <button
          className="icon-button"
          onClick={() => setHelp(!help)}
          aria-label="Show getting started guide"
          aria-expanded={help}
        >
          <CircleHelp size={20} />
        </button>
      </header>
      {help && (
        <aside className="help-panel">
          <button
            className="icon-button"
            onClick={() => setHelp(false)}
            aria-label="Close guide"
          >
            <X size={18} />
          </button>
          <h2>Your code, made visible.</h2>
          <p>
            Paste code or upload a file, then select{" "}
            <strong>Analyze source</strong>. Choose a function from the
            inventory or diagram to explore its immediate callers, dependencies,
            and data flow. Click a node or edge to highlight its source.
          </p>
          <p>
            <strong>Explain function</strong> creates a five-part learning guide
            and tests. <strong>Run tests</strong> executes generated tests
            inside an isolated Docker container. These features require a model
            connection in <strong>LLM settings</strong>; test execution also
            requires the runner image.
          </p>
          <p>
            Use Ctrl/Cmd + Enter in the editor to analyze. Editing your source
            clears the previous analysis.
          </p>
        </aside>
      )}
      <main>
        <section className="workspace-heading">
          <div>
            <p className="eyebrow">THE CODE EXPLORER</p>
            <h1>
              From source to understanding<span>.</span>
            </h1>
            <p className="subtitle">
              Explore structure, follow the data, and make sense of every
              function.
            </p>
          </div>
          <div className="service-status">
            <button
              onClick={() => void refreshCapabilities()}
              className="connection"
              title="Refresh backend capabilities"
            >
              <span
                className={`status-dot ${apiOnline === true ? "online" : apiOnline === false ? "offline" : ""}`}
              />
              {apiOnline === null
                ? "Connecting to API"
                : apiOnline
                  ? "Analysis ready"
                  : "API offline"}
              <RefreshCw size={12} />
            </button>
            <button
              className="connection"
              onClick={() => setSettingsOpen(true)}
              aria-haspopup="dialog"
            >
              <Sparkles size={13} />
              {aiReady ? "Explanations enabled" : "Connect an LLM"}
            </button>
            <span>
              <ShieldCheck size={13} />
              {sandboxReady ? "Sandbox ready" : "Sandbox unavailable"}
            </span>
          </div>
        </section>
        {apiOnline === false && (
          <div className="notice">
            Start the backend on port 8000 to analyze code. See the project
            README for the setup commands.
          </div>
        )}
        <div role="alert" className={`error-banner ${error ? "" : "hidden"}`}>
          <span>{error}</span>
          <button
            className="icon-button"
            onClick={() => setError(null)}
            aria-label="Dismiss error"
          >
            <X size={16} />
          </button>
        </div>
        <div className="workbench">
          <section className="source-panel panel" aria-label="Source workspace">
            <div className="panel-title">
              <span>
                <FileCode2 size={17} />
                Source code
              </span>
              <div className="source-actions">
                <select
                  aria-label="Load example"
                  value=""
                  onChange={(event) =>
                    loadSample(event.target.value as keyof typeof samples)
                  }
                >
                  <option value="" disabled>
                    Load example
                  </option>
                  <option value="python">Python · checkout</option>
                  <option value="javascript">JavaScript · checkout</option>
                  <option value="typescript">TypeScript · checkout</option>
                </select>
                <button
                  className="icon-button"
                  title="Upload source file"
                  aria-label="Upload source file"
                  onClick={() => upload.current?.click()}
                >
                  <Upload size={17} />
                </button>
                <input
                  hidden
                  ref={upload}
                  type="file"
                  accept=".py,.js,.ts,.mjs,.cjs"
                  onChange={(event) => void readFile(event)}
                />
              </div>
            </div>
            <div className="file-bar">
              <span className="file-tab">
                <span className="file-indicator" />
                <input
                  aria-label="Source filename"
                  value={filename}
                  placeholder="snippet.py"
                  onChange={(event) => {
                    invalidate();
                    setFilename(event.target.value);
                  }}
                />
              </span>
              <select
                aria-label="Source language"
                value={language}
                onChange={(event) => {
                  invalidate();
                  setLanguage(event.target.value);
                }}
              >
                <option value="">Auto-detect</option>
                <option value="python">Python</option>
                <option value="javascript">JavaScript</option>
                <option value="typescript">TypeScript</option>
              </select>
            </div>
            <div className="editor-container">
              <Suspense
                fallback={
                  <div className="empty-state">Loading source editor…</div>
                }
              >
                <CodeEditor
                  code={code}
                  language={editorLanguage}
                  onChange={editCode}
                  span={highlight}
                  onLineSelect={(line) => {
                    const matches = analysis?.ir.symbols.callables
                      .filter(
                        (item) =>
                          item.span.start_line <= line &&
                          item.span.end_line >= line,
                      )
                      .sort(
                        (a, b) =>
                          a.span.end_line -
                          a.span.start_line -
                          (b.span.end_line - b.span.start_line),
                      );
                    if (matches?.[0])
                      selectSymbol(matches[0].id, matches[0].span);
                  }}
                />
              </Suspense>
            </div>
            <div className="editor-footer">
              <span>
                {code.split("\n").length} lines
                <span className="separator">·</span>Source stays editable
              </span>
              <button
                id="analyze-source"
                className="button primary"
                disabled={analyzing || !code.trim()}
                onClick={() => void analyze()}
              >
                {analyzing ? (
                  <LoaderCircle className="spin" size={16} />
                ) : (
                  <GitBranch size={16} />
                )}
                {analyzing ? "Analyzing…" : "Analyze source"}
              </button>
            </div>
            <div className="inventory">
              <div
                className="inventory-tabs"
                role="tablist"
                aria-label="Symbol inventory"
              >
                {(["functions", "variables", "imports"] as const).map(
                  (item) => (
                    <button
                      role="tab"
                      aria-selected={inventory === item}
                      key={item}
                      className={inventory === item ? "active" : ""}
                      onClick={() => setInventory(item)}
                    >
                      {item}
                      <span>
                        {!analysis
                          ? "—"
                          : item === "functions"
                            ? analysis.ir.symbols.callables.length
                            : item === "variables"
                              ? analysis.ir.symbols.variables.length
                              : analysis.ir.dependencies.length}
                      </span>
                    </button>
                  ),
                )}
              </div>
              <div className="inventory-list">
                {!analysis ? (
                  <p className="muted inventory-empty">
                    Analyze your source to discover its symbols.
                  </p>
                ) : inventory === "functions" ? (
                  analysis.ir.symbols.callables.length ? (
                    analysis.ir.symbols.callables.map((item) => (
                      <button
                        className={`inventory-item ${item.id === selectedId ? "active" : ""}`}
                        key={item.id}
                        onClick={() => selectSymbol(item.id, item.span)}
                      >
                        <Braces size={14} />
                        <span>
                          {item.qualname}
                          <small>
                            ({item.parameters.map((p) => p.name).join(", ")})
                          </small>
                        </span>
                        <span className="line-label">
                          L{item.span.start_line}
                        </span>
                      </button>
                    ))
                  ) : (
                    <p className="inventory-empty muted">
                      No callable definitions found.
                    </p>
                  )
                ) : inventory === "variables" ? (
                  analysis.ir.symbols.variables.length ? (
                    analysis.ir.symbols.variables.map((item) => (
                      <button
                        className="inventory-item"
                        key={item.id}
                        onClick={() => setHighlight(item.span)}
                      >
                        <Code2 size={14} />
                        <span>
                          {item.name}
                          <small>
                            {item.declared_type ||
                              item.inferred_shape ||
                              "unknown"}{" "}
                            · {item.scope}
                          </small>
                        </span>
                        <span className="line-label">
                          L{item.span.start_line}
                        </span>
                      </button>
                    ))
                  ) : (
                    <p className="inventory-empty muted">No variables found.</p>
                  )
                ) : analysis.ir.dependencies.length ? (
                  analysis.ir.dependencies.map((item) => (
                    <button
                      className="inventory-item"
                      key={item.id}
                      onClick={() => setHighlight(item.span)}
                    >
                      <Layers size={14} />
                      <span>
                        {item.name}
                        <small>{item.category.replace(/_/g, " ")}</small>
                      </span>
                      <span className="line-label">
                        L{item.span.start_line}
                      </span>
                    </button>
                  ))
                ) : (
                  <p className="inventory-empty muted">No imports found.</p>
                )}
              </div>
            </div>
          </section>
          <section
            className="results-panel panel"
            aria-label="Analysis results"
          >
            <div
              className="results-tabs"
              role="tablist"
              aria-label="Analysis views"
            >
              {(
                [
                  { id: "structure", label: "Structure", icon: GitBranch },
                  { id: "explanation", label: "Explanation", icon: Sparkles },
                  { id: "tests", label: "Tests & simulation", icon: Play },
                ] as const
              ).map(({ id, label, icon: Icon }) => (
                <button
                  role="tab"
                  aria-selected={tab === id}
                  key={id}
                  className={tab === id ? "active" : ""}
                  onClick={() => setTab(id)}
                >
                  <Icon size={16} />
                  {label}
                  {id === "tests" && execution && (
                    <span
                      className={`mini-badge status-${execution.execution.status}`}
                    >
                      {execution.execution.status}
                    </span>
                  )}
                </button>
              ))}
              <button
                className="icon-button export-button"
                title="Download JSON intermediate representation"
                aria-label="Download analysis JSON"
                disabled={!analysis}
                onClick={exportIR}
              >
                <Download size={17} />
              </button>
            </div>
            <div className="target-bar">
              <span className="target-label">FOCUS</span>
              <div className="target-select">
                <select
                  aria-label="Selected function"
                  value={selectedId}
                  disabled={!analysis?.ir.symbols.callables.length || analyzing}
                  onChange={(event) => {
                    const item = analysis?.ir.symbols.callables.find(
                      (fn) => fn.id === event.target.value,
                    );
                    if (item) selectSymbol(item.id, item.span);
                  }}
                >
                  {!selectedId && (
                    <option value="">Select a function after analysis</option>
                  )}
                  {analysis?.ir.symbols.callables.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.qualname}
                    </option>
                  ))}
                </select>
                <ChevronDown size={14} />
              </div>
              {selected && (
                <span className="target-location">
                  L{selected.span.start_line}–{selected.span.end_line}
                </span>
              )}
            </div>
            {analysis?.ir.metadata.diagnostics.map((diagnostic, index) => (
              <div key={index} className="diagnostic">
                {diagnostic.message}
              </div>
            ))}
            {tab === "structure" && (
              <>
                <div className="diagram-toolbar">
                  <div className="segmented" aria-label="Diagram view">
                    <button
                      aria-pressed={view === "class"}
                      className={view === "class" ? "active" : ""}
                      onClick={() => setView("class")}
                    >
                      Class & component
                    </button>
                    <button
                      aria-pressed={view === "dataflow"}
                      className={view === "dataflow" ? "active" : ""}
                      onClick={() => setView("dataflow")}
                    >
                      Data flow
                    </button>
                  </div>
                  <span className="graph-count">
                    {diagram
                      ? `${diagram.nodes.length} nodes · ${diagram.edges.length} edges`
                      : ""}
                  </span>
                </div>
                <div className="diagram-container">
                  {analysis && diagram?.nodes.length ? (
                    <Suspense
                      fallback={
                        <div className="empty-state">Loading diagram…</div>
                      }
                    >
                      <Diagram
                        diagram={diagram}
                        selectedId={selectedId}
                        onSelect={selectSymbol}
                        testStatus={
                          execution
                            ? {
                                symbolId: execution.target_symbol_id,
                                status: execution.execution.status,
                              }
                            : null
                        }
                      />
                    </Suspense>
                  ) : (
                    <div className="empty-state">
                      <span className="empty-icon">
                        <GitBranch size={32} />
                      </span>
                      <h2>
                        {sliceLoading
                          ? "Tracing the connections…"
                          : analysis
                            ? "No structure in this view"
                            : "Every function has a story."}
                      </h2>
                      <p>
                        {analysis
                          ? "Choose a function or switch diagram views to explore your source."
                          : "Analyze the example or bring your own code. Its functions, classes, and connections will appear here."}
                      </p>
                      {!analysis && (
                        <button
                          className="button secondary"
                          onClick={() => void analyze()}
                          disabled={analyzing}
                        >
                          {analyzing ? "Analyzing…" : "Explore the example"}
                        </button>
                      )}
                    </div>
                  )}
                </div>
                <div className="diagram-legend">
                  <span>
                    <i className="legend-callable" />
                    Function
                  </span>
                  <span>
                    <i className="legend-container" />
                    Class
                  </span>
                  <span>
                    <i className="legend-dependency" />
                    Dependency
                  </span>
                  <span className="legend-hint">
                    Click any element to locate its source
                  </span>
                </div>
                <div className="focus-summary">
                  <div>
                    <p className="eyebrow">FUNCTION CONTEXT</p>
                    <h3>
                      {selected?.qualname || "Choose your starting point"}
                    </h3>
                    <p>
                      {selected
                        ? `${selected.parameters.length} parameters · ${selected.return_type || "return type unspecified"}`
                        : "A focused view of one function and its immediate connections."}
                    </p>
                  </div>
                  {slice && (
                    <div className="context-counts">
                      <span>
                        <strong>{slice.upstream_callables.length}</strong>
                        callers
                      </span>
                      <span>
                        <strong>{slice.downstream_callables.length}</strong>
                        callees
                      </span>
                      <span>
                        <strong>{slice.data_flows.length}</strong>flow steps
                      </span>
                    </div>
                  )}
                </div>
              </>
            )}
            {tab === "explanation" && (
              <div className="content-scroll">
                <div className="content-heading">
                  <div>
                    <p className="eyebrow">MAKE IT CLICK</p>
                    <h2>A guided tour of your function.</h2>
                  </div>
                  <button
                    className="button primary"
                    disabled={!selected || busy || analyzing}
                    onClick={explain}
                  >
                    {generating ? (
                      <LoaderCircle className="spin" size={16} />
                    ) : (
                      <Sparkles size={16} />
                    )}
                    {generating
                      ? "Explaining…"
                      : Object.keys(sections).length
                        ? "Explain again"
                        : "Explain function"}
                  </button>
                </div>
                {!aiReady && (
                  <div className="notice">
                    <button
                      className="inline-link"
                      onClick={() => setSettingsOpen(true)}
                    >
                      Connect an LLM
                    </button>{" "}
                    to generate explanations. Structural analysis is available
                    without one.
                  </div>
                )}
                {generating && (
                  <div className="generation-progress">
                    <LoaderCircle size={18} className="spin" />
                    <span>
                      Building a guide grounded in the selected function.
                      Checking annotations before they appear…
                    </span>
                  </div>
                )}
                {Object.keys(sections).length ? (
                  <div className="learning-sections">
                    {(
                      Object.keys(sectionNames) as Array<keyof DebunkSections>
                    ).map(
                      (name) =>
                        sections[name] && (
                          <article key={name}>
                            <h3>{sectionNames[name]}</h3>
                            {name === "annotated_code" ? (
                              <pre>
                                <code>{sections.annotated_code}</code>
                              </pre>
                            ) : name === "prerequisite_concepts" ? (
                              <div className="concept-grid">
                                {sections.prerequisite_concepts?.map(
                                  (concept) => (
                                    <div className="concept" key={concept.name}>
                                      <strong>{concept.name}</strong>
                                      <p>{concept.explanation}</p>
                                    </div>
                                  ),
                                )}
                              </div>
                            ) : (
                              <p className="prose">
                                {sections[name] as string}
                              </p>
                            )}
                          </article>
                        ),
                    )}
                  </div>
                ) : (
                  !generating && (
                    <div className="learning-placeholder">
                      <Sparkles size={28} />
                      <h3>Understand the why behind the code.</h3>
                      <p>
                        Get a plain-language analogy, documented source, a
                        step-by-step walkthrough, and concepts worth learning
                        next.
                      </p>
                      <div className="section-preview">
                        {Object.values(sectionNames).map((name) => (
                          <span key={name}>
                            <Check size={14} />
                            {name}
                          </span>
                        ))}
                      </div>
                    </div>
                  )
                )}
                {qa?.passed && (
                  <div className="qa-note">
                    <ShieldCheck size={15} />
                    Structural checks passed. Walkthroughs are illustrative; run
                    tests to check behavior.
                  </div>
                )}
              </div>
            )}
            {tab === "tests" && (
              <div className="content-scroll">
                <div className="content-heading">
                  <div>
                    <p className="eyebrow">FOLLOW THE DATA</p>
                    <h2>Put the function to the test.</h2>
                  </div>
                  <button
                    className="button primary"
                    disabled={
                      !selected ||
                      !sandboxReady ||
                      (!aiReady && !suite) ||
                      busy ||
                      analyzing
                    }
                    onClick={() => void runSimulation()}
                  >
                    {simulating ? (
                      <LoaderCircle size={16} className="spin" />
                    ) : (
                      <Play size={16} />
                    )}
                    {simulating ? "Running…" : "Run tests"}
                  </button>
                </div>
                <div className="sandbox-note">
                  <ShieldCheck size={17} />
                  <p>
                    Tests run in an isolated container with no network, limited
                    resources, and a 10-second execution limit.
                  </p>
                </div>
                {!sandboxReady && (
                  <div className="notice">
                    {capabilities?.sandbox_message ||
                      "Connect the backend and set up Docker to enable simulation."}
                  </div>
                )}
                {!aiReady && !suite && (
                  <div className="notice">
                    <button
                      className="inline-link"
                      onClick={() => setSettingsOpen(true)}
                    >
                      Connect an LLM
                    </button>{" "}
                    to generate the test suite.
                  </div>
                )}
                {simulating && (
                  <div className="generation-progress">
                    <LoaderCircle size={18} className="spin" />
                    Generating and validating tests, then running the sandbox…
                  </div>
                )}
                {execution && (
                  <div className="test-results">
                    <div className="result-summary">
                      <span
                        className={`result-status status-${execution.execution.status}`}
                      >
                        {execution.execution.status}
                      </span>
                      <span>
                        {execution.execution.tests.length} tests ·{" "}
                        {execution.execution.duration_seconds.toFixed(2)}s
                      </span>
                    </div>
                    {execution.execution.tests.map((test, index) => (
                      <div
                        className="test-case"
                        key={`${test.nodeid}-${index}`}
                      >
                        <span
                          className={`test-outcome outcome-${test.outcome}`}
                        >
                          {test.outcome === "passed" ? (
                            <Check size={16} />
                          ) : test.outcome === "skipped" ? (
                            "—"
                          ) : (
                            <X size={16} />
                          )}
                        </span>
                        <div>
                          <strong>{test.name}</strong>
                          <small>
                            {test.outcome} · {test.duration.toFixed(3)}s
                          </small>
                          {test.message && <pre>{test.message}</pre>}
                        </div>
                      </div>
                    ))}
                    {execution.execution.stderr && (
                      <pre className="test-error">
                        {execution.execution.stderr}
                      </pre>
                    )}
                    {execution.execution.stdout && (
                      <details>
                        <summary>Runner output</summary>
                        <pre>{execution.execution.stdout}</pre>
                      </details>
                    )}
                  </div>
                )}
                {testCode ? (
                  <article className="test-source">
                    <h3>Generated test suite</h3>
                    {suite?.mock_summary && (
                      <p className="muted">{suite.mock_summary}</p>
                    )}
                    <pre>
                      <code>{testCode}</code>
                    </pre>
                  </article>
                ) : (
                  !simulating && (
                    <div className="learning-placeholder">
                      <Play size={28} />
                      <h3>See what holds up.</h3>
                      <p>
                        Generate tests for normal inputs, boundaries, and data
                        transformations. Each result is linked to the selected
                        function.
                      </p>
                    </div>
                  )
                )}
              </div>
            )}
          </section>
        </div>
        <footer className="workspace-footer">
          <span>
            <ShieldCheck size={13} />
            Source analysis never executes your code.
          </span>
          <span>Python · JavaScript · TypeScript</span>
          <span>
            CodeDebunker<span className="footer-version">v1.0</span>
          </span>
        </footer>
      </main>
      {settingsOpen && (
        <LLMSettingsDialog
          onClose={() => setSettingsOpen(false)}
          onSaved={() => {
            resetLearning();
            setError(null);
            setSettingsOpen(false);
            void refreshCapabilities();
          }}
        />
      )}
    </div>
  );
}

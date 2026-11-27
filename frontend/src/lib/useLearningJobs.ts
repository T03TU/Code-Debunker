import { useEffect, useRef, useState } from "react";
import { generateTestCases, simulate, streamDebunk } from "@/lib/api";
import { explanationSectionNames } from "@/lib/artifacts";
import type {
  DebunkSections,
  GenerationModel,
  QAResult,
  SimulateResponse,
  TestScope,
  TestSuite,
} from "@/types/api";

interface LearningResult {
  sections: Partial<DebunkSections>;
  suite: TestSuite | null;
  qa: QAResult | null;
  execution: SimulateResponse | null;
  explaining: boolean;
  generatingTests: boolean;
  simulating: boolean;
  error: string | null;
  explanationModel: GenerationModel | null;
  testModel: GenerationModel | null;
}

interface Operation {
  key: string;
  revision: number;
  cancel: () => void;
}

export interface RunningLearningJob {
  targetId: string | null;
  scope: TestScope;
  kind: "explanation" | "tests" | "simulation";
}

const emptyResult = (): LearningResult => ({
  sections: {},
  suite: null,
  qa: null,
  execution: null,
  explaining: false,
  generatingTests: false,
  simulating: false,
  error: null,
  explanationModel: null,
  testModel: null,
});
const empty = emptyResult();
const keyFor = (targetId: string | undefined, scope: TestScope) =>
  scope === "flow" ? "flow" : `function:${targetId}`;
const errorMessage = (error: unknown) =>
  error instanceof Error ? error.message : "Something went wrong.";

/** Jobs belong to their source and target, independently of the visible selection. */
export function useLearningJobs() {
  const [results, setResults] = useState<Record<string, LearningResult>>({});
  const revision = useRef(0);
  const operations = useRef(new Map<string, Operation>());

  function cancelAll() {
    revision.current++;
    for (const operation of operations.current.values()) operation.cancel();
    operations.current.clear();
  }

  useEffect(() => () => cancelAll(), []);

  function reset() {
    cancelAll();
    setResults({});
  }

  function begin(key: string): Operation | null {
    if (operations.current.has(key)) return null;
    const operation = { key, revision: revision.current, cancel: () => {} };
    operations.current.set(key, operation);
    return operation;
  }

  function update(
    operation: Operation,
    change: (result: LearningResult) => LearningResult,
  ) {
    if (
      revision.current !== operation.revision ||
      operations.current.get(operation.key) !== operation
    ) return;
    setResults((previous) => revision.current !== operation.revision
      ? previous
      : {
          ...previous,
          [operation.key]: change(previous[operation.key] ?? emptyResult()),
        },
    );
  }

  function finish(operation: Operation) {
    update(operation, (result) => ({
      ...result, explaining: false, generatingTests: false, simulating: false,
    }));
    if (operations.current.get(operation.key) === operation)
      operations.current.delete(operation.key);
  }

  function explain(analysisId: string, targetId: string) {
    const operation = begin(keyFor(targetId, "function"));
    if (!operation) return;
    update(operation, () => ({ ...emptyResult(), explaining: true }));
    try {
      const stream = streamDebunk(analysisId, targetId, (event) => {
        if (event.type === "slice_ready") {
          update(operation, (result) => ({ ...result, explanationModel: event.generation_model ?? null }));
        } else if (event.type === "section" && Object.prototype.hasOwnProperty.call(explanationSectionNames, event.name)) {
          try {
            const content = event.name === "prerequisite_concepts" ? JSON.parse(event.content) : event.content;
            update(operation, (result) => ({ ...result, sections: { ...result.sections, [event.name]: content } }));
          } catch {
            update(operation, (result) => ({ ...result, error: "The explanation contained an invalid section. Please retry." }));
          }
        } else if (event.type === "tests") {
          update(operation, (result) => ({ ...result, suite: event, testModel: event.generation_model ?? result.explanationModel }));
        } else if (event.type === "qa_result") {
          update(operation, (result) => ({ ...result, qa: event }));
        } else if (event.type === "error") {
          update(operation, (result) => ({ ...result, error: event.message }));
        }
      }, () => finish(operation));
      operation.cancel = () => stream.close();
    } catch (error) {
      update(operation, (result) => ({ ...result, error: errorMessage(error) }));
      finish(operation);
    }
  }

  async function generateCases(analysisId: string, targetId: string | undefined, scope: TestScope) {
    const operation = begin(keyFor(targetId, scope));
    if (!operation) return;
    const controller = new AbortController();
    operation.cancel = () => controller.abort();
    update(operation, (result) => ({ ...result, suite: null, testModel: null, execution: null, generatingTests: true, error: null }));
    try {
      const response = await generateTestCases(analysisId, targetId, scope, controller.signal);
      update(operation, (result) => ({ ...result, suite: response.suite, testModel: response.generation_model ?? null }));
    } catch (error) {
      if (!controller.signal.aborted) update(operation, (result) => ({ ...result, error: errorMessage(error) }));
    } finally {
      finish(operation);
    }
  }

  async function runTests(analysisId: string, targetId: string | undefined, scope: TestScope) {
    const operation = begin(keyFor(targetId, scope));
    if (!operation) return;
    const controller = new AbortController();
    operation.cancel = () => controller.abort();
    update(operation, (result) => ({ ...result, execution: null, simulating: true, error: null }));
    try {
      const response = await simulate(analysisId, targetId, scope, controller.signal);
      update(operation, (result) => ({ ...result, execution: response,
        suite: response.suite ?? result.suite,
        testModel: response.suite ? response.generation_model ?? null : result.testModel,
      }));
    } catch (error) {
      if (!controller.signal.aborted) update(operation, (result) => ({ ...result, error: errorMessage(error) }));
    } finally {
      finish(operation);
    }
  }

  function dismissError(targetId: string | undefined, scope: TestScope) {
    const key = keyFor(targetId, scope);
    setResults((previous) => previous[key] ? { ...previous, [key]: { ...previous[key], error: null } } : previous);
  }

  const runningJobs: RunningLearningJob[] = Object.entries(results).flatMap(([key, result]) => {
    const kind = result.explaining ? "explanation" : result.generatingTests ? "tests" : result.simulating ? "simulation" : null;
    return kind ? [{ targetId: key === "flow" ? null : key.slice("function:".length), scope: key === "flow" ? "flow" : "function", kind }] : [];
  });

  return {
    getResult: (targetId: string | undefined, scope: TestScope = "function") => results[keyFor(targetId, scope)] ?? empty,
    explain,
    generateCases,
    runTests,
    reset,
    dismissError,
    runningJobs,
  };
}

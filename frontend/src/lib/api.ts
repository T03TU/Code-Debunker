import type {
  AnalyzeResponse,
  IRSlice,
  SimulateResponse,
  UMLDiagram,
} from "@/types/api";

const BASE = "/api";

async function readResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    const detail =
      typeof body.detail === "string"
        ? body.detail
        : JSON.stringify(body.detail);
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return res.json();
}

export interface Capabilities {
  languages: string[];
  llm_configured: boolean;
  sandbox_available: boolean;
  sandbox_message: string;
  max_source_bytes: number;
}

export async function getCapabilities(): Promise<Capabilities> {
  return readResponse(await fetch(`${BASE}/capabilities`));
}

export async function analyzeCode(
  code: string,
  filename?: string,
  language?: string,
): Promise<AnalyzeResponse> {
  const res = await fetch(`${BASE}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code, filename, language }),
  });
  return readResponse(res);
}

export async function getSlice(
  analysisId: string,
  symbolId?: string,
): Promise<{ slice: IRSlice; dataflow_diagram: UMLDiagram }> {
  const url = new URL(`${BASE}/slice/${analysisId}`, location.origin);
  if (symbolId) url.searchParams.set("symbol_id", symbolId);
  const res = await fetch(url.toString());
  return readResponse(res);
}

export async function simulate(
  analysisId: string,
  targetSymbolId?: string,
): Promise<SimulateResponse> {
  const res = await fetch(`${BASE}/simulate/${analysisId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_symbol_id: targetSymbolId ?? null }),
  });
  return readResponse(res);
}

export type StreamEvent =
  | { type: "slice_ready"; target_symbol_id: string; target_name: string }
  | { type: "section"; name: string; content: string }
  | {
      type: "tests";
      test_code: string;
      mock_summary: string;
      test_case_names: string[];
    }
  | { type: "qa_result"; passed: boolean; errors: string[] }
  | { type: "done" }
  | { type: "error"; message: string };

export function streamDebunk(
  analysisId: string,
  symbolId: string | undefined,
  onEvent: (event: StreamEvent) => void,
  onClose?: () => void,
): EventSource {
  const url = new URL(`${BASE}/stream/${analysisId}`, location.origin);
  if (symbolId) url.searchParams.set("symbol_id", symbolId);

  const es = new EventSource(url.toString());
  let finished = false;

  const handleEvent = (eventType: string, raw: string) => {
    try {
      const data = JSON.parse(raw);
      if (eventType === "section") {
        onEvent({ type: "section", name: data.name, content: data.content });
      } else if (eventType === "tests") {
        onEvent({ type: "tests", ...data });
      } else if (eventType === "qa_result") {
        onEvent({
          type: "qa_result",
          passed: data.passed,
          errors: data.errors,
        });
      } else if (eventType === "slice_ready") {
        onEvent({ type: "slice_ready", ...data });
      } else if (eventType === "done") {
        finished = true;
        onEvent({ type: "done" });
        es.close();
        onClose?.();
      } else if (eventType === "error") {
        finished = true;
        onEvent({ type: "error", message: data.message });
        es.close();
        onClose?.();
      }
    } catch {
      // ignore parse errors
    }
  };

  for (const evt of [
    "section",
    "tests",
    "qa_result",
    "slice_ready",
    "done",
    "error",
  ]) {
    es.addEventListener(evt, (e: Event) =>
      handleEvent(evt, (e as MessageEvent).data),
    );
  }

  es.onerror = () => {
    if (finished) return;
    finished = true;
    es.close();
    onEvent({ type: "error", message: "SSE connection lost" });
    onClose?.();
  };

  return es;
}

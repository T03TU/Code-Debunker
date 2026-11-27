import type { DebunkSections, GenerationModel, SimulateResponse, TestSuite } from "@/types/api";

interface ArtifactContext {
  filename: string;
  language: string;
  source: string;
  targetName: string;
  scope: "function" | "flow";
  generatedAt?: string;
  generationModel?: GenerationModel | null;
}

type ExplanationDraft = ArtifactContext & {
  kind: "explanation";
  sections: Partial<DebunkSections>;
};

type TestsDraft = ArtifactContext & {
  kind: "tests";
  suite: TestSuite;
  execution?: SimulateResponse;
};

export type ArtifactDraft = ExplanationDraft | TestsDraft;
export type SavedArtifact = ArtifactDraft & {
  id: string;
  savedAt: string;
  generatedAt: string;
};

export const explanationSectionNames = {
  language_identification: "Language identification",
  feynman_explanation: "The everyday explanation",
  annotated_code: "Annotated code",
  simulated_walkthrough: "Execution walkthrough",
  prerequisite_concepts: "Concepts to know",
} satisfies Record<keyof DebunkSections, string>;

const databaseName = "codedebunker-library";
const storeName = "artifacts";
const unavailable =
  "Browser storage is unavailable. You can still download a copy.";

function openLibrary(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(databaseName, 1);
    let blocked = false;
    request.onupgradeneeded = () => {
      request.result.createObjectStore(storeName, { keyPath: "id" });
    };
    request.onblocked = () => {
      blocked = true;
      reject(new Error("Close other CodeDebunker tabs and try again."));
    };
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      const database = request.result;
      if (blocked) {
        database.close();
        return;
      }
      database.onversionchange = () => database.close();
      resolve(database);
    };
  });
}

async function transact<T>(
  mode: IDBTransactionMode,
  operation: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  let database: IDBDatabase | undefined;
  try {
    database = await openLibrary();
    const transaction = database.transaction(storeName, mode);
    const request = operation(transaction.objectStore(storeName));
    return await new Promise<T>((resolve, reject) => {
      transaction.oncomplete = () => resolve(request.result);
      transaction.onabort = () => reject(transaction.error ?? request.error);
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "QuotaExceededError") {
      throw new Error(
        "Browser storage is full. Remove a saved item or download a copy.",
      );
    }
    if (error instanceof Error && !(error instanceof DOMException)) {
      // Only the blocked database message is safe to show directly.
      if (error.message === "Close other CodeDebunker tabs and try again.")
        throw error;
    }
    throw new Error(unavailable);
  } finally {
    database?.close();
  }
}

export async function saveArtifact(
  draft: ArtifactDraft,
): Promise<SavedArtifact> {
  const savedAt = new Date().toISOString();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  const artifact: SavedArtifact = {
    ...draft,
    id: Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join(
      "",
    ),
    savedAt,
    generatedAt: draft.generatedAt ?? savedAt,
  };
  await transact("readwrite", (store) => store.add(artifact));
  return artifact;
}

export async function listArtifacts(): Promise<SavedArtifact[]> {
  const items: SavedArtifact[] = await transact("readonly", (store) =>
    store.getAll(),
  );
  return items.sort((a, b) => b.savedAt.localeCompare(a.savedAt));
}

export async function deleteArtifact(id: string): Promise<void> {
  await transact("readwrite", (store) => store.delete(id));
}

function codeBlock(source: string, language: string) {
  const fence = "`".repeat(
    Math.max(3, ...(source.match(/`+/g) ?? []).map((run) => run.length + 1)),
  );
  return `${fence}${language.replace(/[^a-z0-9_-]/gi, "")}\n${source}\n${fence}`;
}

function metadataText(value: string) {
  return value.replace(/\s+/g, " ").replace(/[\\`*_{}\[\]()#+.!<>]/g, "\\$&");
}

export function artifactModelLabel(artifact: ArtifactDraft) {
  return artifact.generationModel
    ? `${artifact.generationModel.model} (${artifact.generationModel.provider})`
    : "Not recorded";
}

function explanationMarkdown(artifact: ExplanationDraft) {
  const lines = [
    `# Explanation for ${metadataText(artifact.targetName)}`,
    "",
    `Source file: ${metadataText(artifact.filename || "Untitled source")}`,
    "",
    `Language: ${metadataText(artifact.language)}`,
    "",
    `Model: ${metadataText(artifactModelLabel(artifact))}`,
  ];
  if (artifact.generatedAt)
    lines.push("", `Generated: ${artifact.generatedAt}`);
  for (const key of Object.keys(
    explanationSectionNames,
  ) as (keyof DebunkSections)[]) {
    const value = artifact.sections[key];
    if (!value) continue;
    lines.push("", `## ${explanationSectionNames[key]}`, "");
    if (Array.isArray(value)) {
      lines.push(
        ...value.map(
          ({ name, explanation }) =>
            `- **${metadataText(name)}** — ${explanation}`,
        ),
      );
    } else {
      lines.push(
        key === "annotated_code" ? codeBlock(value, artifact.language) : value,
      );
    }
  }
  return lines.join("\n") + "\n";
}

function safeFilePart(value: string, fallback: string) {
  return (
    value
      .replace(/[^a-z0-9_-]+/gi, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 55) || fallback
  );
}

function fileStem(artifact: ArtifactDraft) {
  const basename = artifact.filename.split(/[\\/]/).pop() ?? "";
  const source = safeFilePart(basename.replace(/\.[^.]+$/, ""), "source");
  const target =
    artifact.scope === "flow"
      ? "full-flow"
      : safeFilePart(artifact.targetName, "function");
  return `${source}-${target}`;
}

function download(content: string, filename: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function downloadArtifact(artifact: ArtifactDraft | SavedArtifact) {
  const stem = fileStem(artifact);
  if (artifact.kind === "explanation") {
    download(
      explanationMarkdown(artifact),
      `${stem}-explanation.md`,
      "text/markdown;charset=utf-8",
    );
  } else {
    download(
      JSON.stringify({ version: 1, ...artifact }, null, 2) + "\n",
      `${stem}-test-cases.json`,
      "application/json",
    );
  }
}

export function downloadTestCode(artifact: TestsDraft) {
  if (!artifact.suite.test_code) return;
  const stem = fileStem(artifact);
  const filename =
    artifact.language === "python"
      ? `test_${stem.replace(/-/g, "_")}.py`
      : `${stem}.test.${artifact.language === "typescript" ? "ts" : "js"}`;
  const attribution = artifact.generationModel
    ? `${artifact.language === "python" ? "#" : "//"} Generated model: ${artifactModelLabel(artifact).replace(/\s+/g, " ")}\n`
    : "";
  download(attribution + artifact.suite.test_code, filename, "text/plain;charset=utf-8");
}

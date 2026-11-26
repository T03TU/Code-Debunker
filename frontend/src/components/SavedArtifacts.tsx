import { useEffect, useRef, useState } from "react";
import {
  Download,
  FileCode2,
  FolderOpen,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import TestScenarios from "@/components/TestScenarios";
import {
  deleteArtifact,
  downloadArtifact,
  downloadTestCode,
  explanationSectionNames,
  listArtifacts,
  type SavedArtifact,
} from "@/lib/artifacts";
import type { DebunkSections } from "@/types/api";
import "./SavedArtifacts.css";

interface Props {
  onClose: () => void;
  initialId?: string;
}

const dates = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

function artifactLabel(artifact: SavedArtifact) {
  if (artifact.kind === "explanation") return "Explanation";
  return artifact.scope === "flow"
    ? "Full flow test cases"
    : "Function test cases";
}

function ExplanationPreview({
  sections,
}: {
  sections: Partial<DebunkSections>;
}) {
  return (
    <div className="learning-sections">
      {(Object.keys(explanationSectionNames) as (keyof DebunkSections)[]).map(
        (key) => {
          const value = sections[key];
          if (!value) return null;
          return (
            <article key={key}>
              <h3>{explanationSectionNames[key]}</h3>
              {Array.isArray(value) ? (
                <ul className="saved-concepts">
                  {value.map(({ name, explanation }, index) => (
                    <li key={index}>
                      <strong>{name}</strong>
                      <p className="prose">{explanation}</p>
                    </li>
                  ))}
                </ul>
              ) : key === "annotated_code" ? (
                <pre>
                  <code>{value}</code>
                </pre>
              ) : (
                <p className="prose">{value}</p>
              )}
            </article>
          );
        },
      )}
    </div>
  );
}

function TestsPreview({
  artifact,
}: {
  artifact: Extract<SavedArtifact, { kind: "tests" }>;
}) {
  const { suite, execution } = artifact;
  const report = execution?.execution;
  return (
    <div className="learning-sections">
      <TestScenarios suite={suite} />
      {!suite.scenarios?.length && suite.test_case_names.length > 0 && (
        <article>
          <h3>Cases</h3>
          <ul className="saved-test-list">
            {suite.test_case_names.map((name, index) => (
              <li key={index}>{name}</li>
            ))}
          </ul>
        </article>
      )}
      {suite.mock_summary && (
        <article>
          <h3>Mocked dependencies</h3>
          <p className="prose">{suite.mock_summary}</p>
        </article>
      )}
      {suite.test_code && (
        <article>
          <h3>Generated test code</h3>
          <pre>
            <code>{suite.test_code}</code>
          </pre>
        </article>
      )}
      {report && (
        <article>
          <h3>Sandbox results</h3>
          <p className="prose">
            {report.status} · {report.duration_seconds.toFixed(2)}s
          </p>
          {report.tests.length > 0 && (
            <ul className="saved-test-list">
              {report.tests.map((item, index) => (
                <li key={index}>
                  {item.name} · {item.outcome}
                  {item.message && <pre>{item.message}</pre>}
                </li>
              ))}
            </ul>
          )}
          {report.stdout && (
            <details>
              <summary>Standard output</summary>
              <pre>{report.stdout}</pre>
            </details>
          )}
          {report.stderr && (
            <details>
              <summary>Standard error</summary>
              <pre>{report.stderr}</pre>
            </details>
          )}
        </article>
      )}
    </div>
  );
}

export default function SavedArtifacts({ onClose, initialId }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const [items, setItems] = useState<SavedArtifact[] | null>(null);
  const [selectedId, setSelectedId] = useState(initialId);
  const [pendingDeletion, setPendingDeletion] = useState<string>();
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState<string>();
  const selected = items?.find((item) => item.id === selectedId) ?? items?.[0];

  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    const previousFocus = document.activeElement;
    const overflow = document.body.style.overflow;
    element.showModal();
    close.current?.focus();
    document.body.style.overflow = "hidden";
    return () => {
      element.close();
      document.body.style.overflow = overflow;
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) {
        previousFocus.focus();
      }
    };
  }, []);

  useEffect(() => {
    let active = true;
    listArtifacts()
      .then((artifacts) => {
        if (active) setItems(artifacts);
      })
      .catch((failure: Error) => {
        if (active) {
          setItems([]);
          setError(failure.message);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  async function remove(id: string) {
    setDeleting(true);
    setError(undefined);
    try {
      await deleteArtifact(id);
      setItems((previous) => previous?.filter((item) => item.id !== id) ?? []);
      setPendingDeletion(undefined);
      close.current?.focus();
    } catch (failure) {
      setError(
        failure instanceof Error
          ? failure.message
          : "Could not remove this item.",
      );
    } finally {
      setDeleting(false);
    }
  }

  return (
    <dialog
      ref={dialog}
      className="settings-dialog saved-dialog"
      aria-labelledby="saved-title"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <header className="settings-header saved-header">
        <div>
          <h2 id="saved-title">Saved library</h2>
          <p className="settings-description">Stored in this browser.</p>
        </div>
        <button
          ref={close}
          className="icon-button"
          aria-label="Close saved library"
          onClick={onClose}
        >
          <X size={20} />
        </button>
      </header>
      {error && (
        <p role="alert" className="saved-error">
          {error}
        </p>
      )}
      {!items ? (
        <p role="status" className="saved-empty">
          Loading saved items…
        </p>
      ) : selected ? (
        <div className="saved-grid">
          <ul className="saved-list" aria-label="Saved items">
            {items.map((item) => (
              <li key={item.id}>
                <button
                  className="saved-item"
                  aria-current={item.id === selected.id ? "true" : undefined}
                  disabled={deleting}
                  onClick={() => {
                    setSelectedId(item.id);
                    setPendingDeletion(undefined);
                    setError(undefined);
                  }}
                >
                  {item.kind === "explanation" ? (
                    <Sparkles size={16} />
                  ) : (
                    <FileCode2 size={16} />
                  )}
                  <span>
                    <strong>{item.targetName}</strong>
                    <small>
                      {artifactLabel(item)} ·{" "}
                      {item.filename || "Untitled source"}
                    </small>
                    <time dateTime={item.savedAt}>
                      {dates.format(new Date(item.savedAt))}
                    </time>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <section
            className="saved-preview"
            aria-label="Saved item preview"
            key={selected.id}
          >
            <p className="eyebrow">{artifactLabel(selected)}</p>
            <h3 className="saved-target">{selected.targetName}</h3>
            <div className="saved-actions">
              <button
                className="button secondary"
                onClick={() => downloadArtifact(selected)}
              >
                <Download size={16} />
                {selected.kind === "explanation"
                  ? "Markdown"
                  : "Test cases JSON"}
              </button>
              {selected.kind === "tests" && selected.suite.test_code && (
                <button
                  className="button secondary"
                  onClick={() => downloadTestCode(selected)}
                >
                  <Download size={16} />
                  Test file
                </button>
              )}
              {pendingDeletion !== selected.id && (
                <button
                  className="icon-button"
                  aria-label="Remove saved item"
                  title="Remove saved item"
                  onClick={() => setPendingDeletion(selected.id)}
                >
                  <Trash2 size={17} />
                </button>
              )}
            </div>
            {pendingDeletion === selected.id && (
              <div className="saved-confirm">
                <p>Remove this item from the library?</p>
                <div className="saved-actions">
                  <button
                    className="button secondary"
                    disabled={deleting}
                    onClick={() => setPendingDeletion(undefined)}
                  >
                    Cancel
                  </button>
                  <button
                    className="button secondary saved-remove"
                    disabled={deleting}
                    onClick={() => void remove(selected.id)}
                  >
                    {deleting ? "Removing…" : "Remove"}
                  </button>
                </div>
              </div>
            )}
            {selected.kind === "explanation" ? (
              <ExplanationPreview sections={selected.sections} />
            ) : (
              <TestsPreview artifact={selected} />
            )}
            <details>
              <summary>Original source</summary>
              <pre>
                <code>{selected.source}</code>
              </pre>
            </details>
          </section>
        </div>
      ) : !error ? (
        <div className="saved-empty">
          <FolderOpen size={28} />
          <h3>No saved items yet</h3>
          <p>
            Generate an explanation or test cases and select Save to add them
            here.
          </p>
        </div>
      ) : null}
    </dialog>
  );
}

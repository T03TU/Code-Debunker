import { useEffect, useRef } from "react";
import Editor, { loader, type OnMount } from "@monaco-editor/react";
import * as monaco from "monaco-editor/editor/editor.api.js";
import "monaco-editor/languages/definitions/python/register.js";
import "monaco-editor/languages/definitions/javascript/register.js";
import "monaco-editor/languages/definitions/typescript/register.js";
import "monaco-editor/language/typescript/monaco.contribution.js";
import EditorWorker from "monaco-editor/editor/editor.worker.js?worker";
import TypeScriptWorker from "monaco-editor/language/typescript/ts.worker.js?worker";
import type { SourceSpan } from "@/types/api";

self.MonacoEnvironment = {
  getWorker: (_id: string, label: string) =>
    label === "typescript" || label === "javascript"
      ? new TypeScriptWorker()
      : new EditorWorker(),
};
loader.config({ monaco });

interface Props {
  code: string;
  language: string;
  onChange: (code: string) => void;
  span: SourceSpan | null;
  onLineSelect: (line: number) => void;
}

export default function CodeEditor({
  code,
  language,
  onChange,
  span,
  onLineSelect,
}: Props) {
  const editor = useRef<monaco.editor.IStandaloneCodeEditor | null>(null);
  const decorations = useRef<monaco.editor.IEditorDecorationsCollection | null>(
    null,
  );
  const onSelect = useRef(onLineSelect);
  onSelect.current = onLineSelect;
  const mounted: OnMount = (instance) => {
    editor.current = instance;
    decorations.current = instance.createDecorationsCollection();
    instance.onMouseDown((event) => {
      if (event.target.position)
        onSelect.current(event.target.position.lineNumber);
    });
    instance.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter, () => {
      document.getElementById("analyze-source")?.click();
    });
  };
  useEffect(() => {
    const instance = editor.current;
    if (!instance || !decorations.current) return;
    decorations.current.set(
      span
        ? [
            {
              range: new monaco.Range(
                span.start_line,
                span.start_col + 1,
                span.end_line,
                span.end_col + 1,
              ),
              options: {
                isWholeLine: true,
                className: "source-highlight",
                linesDecorationsClassName: "source-gutter",
              },
            },
          ]
        : [],
    );
    if (span) instance.revealLineInCenterIfOutsideViewport(span.start_line);
  }, [span]);
  return (
    <Editor
      value={code}
      language={language}
      theme="vs-dark"
      onMount={mounted}
      onChange={(value) => onChange(value ?? "")}
      loading={<div className="empty-state">Loading source editor…</div>}
      options={{
        fontSize: 14,
        fontFamily: "'JetBrains Mono', Consolas, monospace",
        minimap: { enabled: false },
        scrollBeyondLastLine: false,
        automaticLayout: true,
        tabSize: 4,
        padding: { top: 20 },
        lineNumbersMinChars: 3,
        renderLineHighlight: "line",
        wordWrap: "on",
        ariaLabel: "Source code to analyze",
        quickSuggestions: false,
      }}
    />
  );
}

"use client";

import CodeMirror from "@uiw/react-codemirror";
import { javascript } from "@codemirror/lang-javascript";
import { markdown } from "@codemirror/lang-markdown";
import { python } from "@codemirror/lang-python";
import { EditorState, Extension } from "@codemirror/state";
import { EditorView, keymap, placeholder as cmPlaceholder } from "@codemirror/view";
import { ButtonHTMLAttributes, CSSProperties, InputHTMLAttributes, KeyboardEventHandler, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes, useMemo, useState } from "react";

const panelStyle: CSSProperties = {
  background: "var(--surface)",
  border: "1px solid var(--border)",
  borderRadius: 12,
  padding: 14,
};

export function PageIntro({ title, description }: { title: string; description: string }) {
  return (
    <>
      <h1 style={{ fontSize: 22, color: "var(--text-bright)", marginBottom: 10 }}>{title}</h1>
      <div style={{ color: "var(--text-dim)", marginBottom: 12 }}>{description}</div>
    </>
  );
}

export function PageShell({ children }: { children: ReactNode }) {
  return (
    <main
      style={{
        padding: 18,
        display: "grid",
        gap: 14,
      }}
    >
      {children}
    </main>
  );
}

export function CardGrid({
  children,
  minWidth = 220,
  gap = 10,
}: {
  children: ReactNode;
  minWidth?: number;
  gap?: number;
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(auto-fit, minmax(${minWidth}px, 1fr))`,
        gap,
      }}
    >
      {children}
    </div>
  );
}

export function DataTable({ children }: { children: ReactNode }) {
  return <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>{children}</table>;
}

export function DataTh({ children }: { children: ReactNode }) {
  return (
    <th
      style={{
        padding: "6px 8px",
        color: "var(--text-dim)",
        textAlign: "left",
        fontWeight: 500,
      }}
    >
      {children}
    </th>
  );
}

export function DataTd({ children, mono = false }: { children: ReactNode; mono?: boolean }) {
  return (
    <td
      style={{
        padding: "7px 8px",
        fontFamily: mono ? "var(--mono)" : undefined,
        fontSize: mono ? 12 : 13,
      }}
    >
      {children}
    </td>
  );
}

export function SectionCard({
  children,
  style,
}: {
  children: ReactNode;
  style?: CSSProperties;
}) {
  return <section style={{ ...panelStyle, ...style }}>{children}</section>;
}

export function SectionTitle({ title }: { title: string }) {
  return <div style={{ color: "var(--text-bright)", fontWeight: 700, marginBottom: 8 }}>{title}</div>;
}

export function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 10,
        padding: 12,
      }}
    >
      <div style={{ color: "var(--text-dim)", fontSize: 12, marginBottom: 6 }}>{label}</div>
      <div style={{ color: "var(--text-bright)", fontSize: 20, fontWeight: 700 }}>{value}</div>
    </div>
  );
}

export function StatusPill({ text, active = false }: { text: string; active?: boolean }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        borderRadius: 999,
        border: "1px solid var(--border)",
        background: active ? "var(--surface)" : "var(--surface2)",
        color: active ? "var(--text-bright)" : "var(--text-dim)",
        padding: "2px 8px",
        fontSize: 11,
        fontWeight: 700,
      }}
    >
      {text}
    </span>
  );
}

export function EmptyState({ text }: { text: string }) {
  return (
    <div
      style={{
        color: "var(--text-dim)",
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 10,
        padding: 14,
      }}
    >
      {text}
    </div>
  );
}

export function ErrorBanner({ text }: { text: string }) {
  return (
    <div
      style={{
        color: "var(--danger)",
        border: "1px solid var(--danger)",
        background: "var(--surface)",
        borderRadius: 10,
        padding: "8px 10px",
        marginBottom: 12,
        fontSize: 13,
      }}
      role="alert"
    >
      {text}
    </div>
  );
}

export function InfoHint({ text }: { text: string }) {
  return <div style={{ color: "var(--text-dim)", fontSize: 12 }}>{text}</div>;
}

const fieldBaseStyle: CSSProperties = {
  border: "1px solid var(--border)",
  borderRadius: 6,
  background: "var(--surface2)",
  color: "var(--text)",
  padding: "8px 10px",
};

const buttonBaseStyle: CSSProperties = {
  borderRadius: 6,
  padding: "8px 14px",
  cursor: "pointer",
  fontWeight: 700,
};

export function TextInput(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} style={{ ...fieldBaseStyle, ...(props.style || {}) }} />;
}

export function SelectInput(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} style={{ ...fieldBaseStyle, ...(props.style || {}) }} />;
}

export function TextAreaInput(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} style={{ ...fieldBaseStyle, ...(props.style || {}) }} />;
}

type CodeEditorLanguage = "text" | "markdown" | "javascript" | "python";

function inferLanguageFromFileName(fileName?: string): CodeEditorLanguage {
  if (!fileName) {
    return "markdown";
  }
  const lower = fileName.toLowerCase();
  if (lower.endsWith(".md") || lower.endsWith(".markdown") || lower.endsWith(".mdx")) {
    return "markdown";
  }
  if (lower.endsWith(".js") || lower.endsWith(".jsx") || lower.endsWith(".ts") || lower.endsWith(".tsx")) {
    return "javascript";
  }
  if (lower.endsWith(".py")) {
    return "python";
  }
  return "markdown";
}

function formatContent(value: string, language: CodeEditorLanguage): string {
  if (!value) {
    return value;
  }

  const normalized = value.replace(/\r\n/g, "\n");
  if (language === "markdown" || language === "text") {
    const lines = normalized.split("\n").map((line) => line.replace(/[ \t]+$/g, ""));
    const formatted = lines.join("\n").replace(/\n{3,}/g, "\n\n");
    return formatted.endsWith("\n") ? formatted : `${formatted}\n`;
  }

  return normalized;
}

type CodeEditorInputProps = {
  value: string;
  onChange: (value: string) => void;
  onKeyDown?: KeyboardEventHandler<HTMLDivElement>;
  language?: CodeEditorLanguage | "auto";
  fileName?: string;
  placeholder?: string;
  required?: boolean;
  showToolbar?: boolean;
  enableFormat?: boolean;
  defaultReadOnly?: boolean;
  style?: CSSProperties;
};

export function CodeEditorInput({
  value,
  onChange,
  onKeyDown,
  language = "markdown",
  fileName,
  placeholder,
  showToolbar = false,
  enableFormat = false,
  defaultReadOnly = false,
  style,
}: CodeEditorInputProps) {
  const [isReadOnly, setIsReadOnly] = useState(defaultReadOnly);
  const [lineWrap, setLineWrap] = useState(true);

  const resolvedLanguage = useMemo<CodeEditorLanguage>(() => {
    if (language === "auto") {
      return inferLanguageFromFileName(fileName);
    }
    return language;
  }, [fileName, language]);

  const extensions = useMemo(() => {
    const languageExtensions: Record<CodeEditorLanguage, Extension[]> = {
      text: [],
      markdown: [markdown()],
      javascript: [javascript({ typescript: true })],
      python: [python()],
    };

    const baseExtensions: Extension[] = [
      ...languageExtensions[resolvedLanguage],
      EditorState.readOnly.of(isReadOnly),
      EditorView.editable.of(!isReadOnly),
    ];

    if (lineWrap) {
      baseExtensions.push(EditorView.lineWrapping);
    }
    if (placeholder) {
      baseExtensions.push(cmPlaceholder(placeholder));
    }
    if (onKeyDown) {
      baseExtensions.push(
        keymap.of([
          {
            key: "Mod-Enter",
            run: () => false,
          },
        ])
      );
    }

    return baseExtensions;
  }, [isReadOnly, lineWrap, onKeyDown, placeholder, resolvedLanguage]);

  function handleFormat() {
    onChange(formatContent(value, resolvedLanguage));
  }

  return (
    <div
      style={{
        ...fieldBaseStyle,
        padding: 0,
        overflow: "hidden",
        borderRadius: 8,
        border: "1px solid var(--border)",
        background: "var(--surface)",
        ...style,
      }}
    >
      {showToolbar && (
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 8,
            padding: "6px 8px",
            borderBottom: "1px solid var(--border)",
            background: "var(--surface2)",
            fontSize: 12,
            color: "var(--text-dim)",
          }}
        >
          <div>语言：{resolvedLanguage}</div>
          <div style={{ display: "flex", gap: 6 }}>
            {enableFormat && (
              <button
                type="button"
                onClick={handleFormat}
                style={{
                  border: "1px solid var(--border)",
                  background: "var(--surface)",
                  color: "var(--text)",
                  borderRadius: 6,
                  fontSize: 12,
                  padding: "3px 8px",
                  cursor: "pointer",
                }}
              >
                格式化
              </button>
            )}
            <button
              type="button"
              onClick={() => setLineWrap((prev) => !prev)}
              style={{
                border: "1px solid var(--border)",
                background: "var(--surface)",
                color: "var(--text)",
                borderRadius: 6,
                fontSize: 12,
                padding: "3px 8px",
                cursor: "pointer",
              }}
            >
              {lineWrap ? "关闭换行" : "自动换行"}
            </button>
            <button
              type="button"
              onClick={() => setIsReadOnly((prev) => !prev)}
              style={{
                border: "1px solid var(--border)",
                background: "var(--surface)",
                color: "var(--text)",
                borderRadius: 6,
                fontSize: 12,
                padding: "3px 8px",
                cursor: "pointer",
              }}
            >
              {isReadOnly ? "切换可编辑" : "切换只读"}
            </button>
          </div>
        </div>
      )}
      <CodeMirror
        value={value}
        onChange={onChange}
        basicSetup={{
          lineNumbers: true,
          highlightActiveLineGutter: true,
          foldGutter: true,
          autocompletion: true,
          bracketMatching: true,
        }}
        extensions={extensions}
        onKeyDown={onKeyDown}
        theme="dark"
        style={{
          minHeight: 120,
        }}
        editable={!isReadOnly}
        spellCheck={false}
      />
      <style jsx global>{`
        .cm-editor {
          background: var(--surface) !important;
          color: var(--text) !important;
          font-family: var(--mono);
          font-size: 12px;
        }
        .cm-editor.cm-focused {
          outline: none !important;
        }
        .cm-content,
        .cm-line {
          font-family: var(--mono);
          line-height: 1.5;
        }
        .cm-gutters {
          background: var(--surface2) !important;
          border-right: 1px solid var(--border);
          color: var(--text-dim);
        }
        .cm-activeLine,
        .cm-activeLineGutter {
          background: rgba(127, 127, 127, 0.12) !important;
        }
      `}</style>
    </div>
  );
}

export function PrimaryButton(props: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      style={{
        ...buttonBaseStyle,
        border: "none",
        background: "var(--accent)",
        color: "#fff",
        ...(props.style || {}),
      }}
    />
  );
}

export function SecondaryButton(props: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      style={{
        ...buttonBaseStyle,
        border: "1px solid var(--border)",
        background: "var(--surface2)",
        color: "var(--text)",
        fontWeight: 500,
        ...(props.style || {}),
      }}
    />
  );
}

export function SuccessButton(props: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      {...props}
      style={{
        ...buttonBaseStyle,
        border: "none",
        background: "var(--success)",
        color: "#fff",
        ...(props.style || {}),
      }}
    />
  );
}

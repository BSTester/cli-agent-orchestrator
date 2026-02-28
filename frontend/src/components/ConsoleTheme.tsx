"use client";

import { ButtonHTMLAttributes, CSSProperties, InputHTMLAttributes, ReactNode, SelectHTMLAttributes, TextareaHTMLAttributes } from "react";

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

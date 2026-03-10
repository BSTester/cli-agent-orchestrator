"use client";

import { useCallback, useEffect, useRef } from "react";
import type { FitAddon } from "@xterm/addon-fit";
import type { Terminal as XTerm } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";

import { SecondaryButton } from "@/components/ConsoleTheme";
import { caoRequest } from "@/lib/cao";

type TerminalDrawerProps = {
  terminalId: string;
  title: string;
  subtitle: string;
  onClose: () => void;
};

export default function TerminalDrawer({ terminalId, title, subtitle, onClose }: TerminalDrawerProps) {
  const terminalContainerRef = useRef<HTMLDivElement | null>(null);
  const terminalRef = useRef<XTerm | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const disconnectTerminal = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (terminalRef.current) {
      terminalRef.current.dispose();
      terminalRef.current = null;
    }
    fitAddonRef.current = null;
  }, []);

  useEffect(() => {
    if (!terminalId || !terminalContainerRef.current) {
      return;
    }

    let disposed = false;
    disconnectTerminal();

    const setupTerminal = async () => {
      const [{ Terminal }, { FitAddon }] = await Promise.all([
        import("@xterm/xterm"),
        import("@xterm/addon-fit"),
      ]);

      if (disposed || !terminalContainerRef.current) {
        return;
      }

      const term = new Terminal({
        convertEol: true,
        cursorBlink: true,
        cursorStyle: "block",
        fontFamily: "var(--terminal-mono)",
        fontSize: 13,
        lineHeight: 1,
        letterSpacing: 0,
        rescaleOverlappingGlyphs: true,
        theme: {
          background: "#0d1117",
          foreground: "#d1d5db",
          cursor: "#6aa0ff",
        },
      });
      const fitAddon = new FitAddon();
      term.loadAddon(fitAddon);
      term.open(terminalContainerRef.current);
      fitAddon.fit();
      term.writeln("正在连接 tmux 终端...");

      terminalRef.current = term;
      fitAddonRef.current = fitAddon;

      const handleResize = () => fitAddon.fit();
      window.addEventListener("resize", handleResize);

      const tokenResult = await caoRequest<{ token: string }>("POST", "/console/ws-token");
      if (!tokenResult.ok || !tokenResult.data?.token) {
        term.writeln("[错误] 获取 WS 令牌失败");
        return;
      }

      const controlPanelHttp =
        process.env.NEXT_PUBLIC_CAO_CONTROL_PANEL_URL ||
        (window.location.port === "3000" ? "http://localhost:8000" : window.location.origin);
      const wsBase = controlPanelHttp.replace(/^http/i, "ws").replace(/\/$/, "");
      const wsUrl = `${wsBase}/console/agents/${terminalId}/tmux/ws?token=${encodeURIComponent(
        tokenResult.data.token
      )}`;

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;
      const emitResize = () => {
        if (ws.readyState !== WebSocket.OPEN) {
          return;
        }
        ws.send(JSON.stringify({ cols: term.cols, rows: term.rows }));
      };
      const sendInput = (text: string) => {
        if (!text || ws.readyState !== WebSocket.OPEN) {
          return;
        }
        ws.send(JSON.stringify({ input: text }));
      };
      const mapKeyboardToAnsi = (event: KeyboardEvent): string | null => {
        if (event.isComposing || event.keyCode === 229) {
          return null;
        }

        const functionKeyMap: Record<string, string> = {
          F1: "\u001bOP",
          F2: "\u001bOQ",
          F3: "\u001bOR",
          F4: "\u001bOS",
          F5: "\u001b[15~",
          F6: "\u001b[17~",
          F7: "\u001b[18~",
          F8: "\u001b[19~",
          F9: "\u001b[20~",
          F10: "\u001b[21~",
          F11: "\u001b[23~",
          F12: "\u001b[24~",
        };

        const keyMap: Record<string, string> = {
          ArrowUp: "\u001b[A",
          ArrowDown: "\u001b[B",
          ArrowRight: "\u001b[C",
          ArrowLeft: "\u001b[D",
          Home: "\u001b[H",
          End: "\u001b[F",
          PageUp: "\u001b[5~",
          PageDown: "\u001b[6~",
          Insert: "\u001b[2~",
          Delete: "\u001b[3~",
          Escape: "\u001b",
        };

        if (event.key in functionKeyMap) {
          return functionKeyMap[event.key];
        }

        if (event.key === "Tab") {
          return event.shiftKey ? "\u001b[Z" : "\t";
        }

        if (event.key === "Enter") {
          return "\r";
        }

        if (event.key === "Backspace") {
          return "\u007f";
        }

        if (event.ctrlKey && !event.altKey && !event.metaKey) {
          if (event.key === " ") {
            return "\u0000";
          }

          if (/^[a-zA-Z]$/.test(event.key)) {
            const upper = event.key.toUpperCase();
            return String.fromCharCode(upper.charCodeAt(0) - 64);
          }

          const ctrlSymbolMap: Record<string, string> = {
            "[": "\u001b",
            "\\": "\u001c",
            "]": "\u001d",
            "^": "\u001e",
            _: "\u001f",
          };

          if (event.key in ctrlSymbolMap) {
            return ctrlSymbolMap[event.key];
          }
        }

        if (event.altKey && !event.ctrlKey && !event.metaKey && event.key.length === 1) {
          return `\u001b${event.key}`;
        }

        if (event.key in keyMap) {
          return keyMap[event.key];
        }

        return null;
      };
      let isComposing = false;
      let imeEchoSuppression = "";
      const resizeObserver = new ResizeObserver(() => {
        fitAddon.fit();
        emitResize();
      });
      resizeObserver.observe(terminalContainerRef.current);

      const helperTextarea = terminalContainerRef.current.querySelector(
        ".xterm-helper-textarea"
      ) as HTMLTextAreaElement | null;
      const handleCompositionStart = () => {
        isComposing = true;
      };
      const handleCompositionEnd = (event: CompositionEvent) => {
        isComposing = false;
        if (event.data) {
          imeEchoSuppression += event.data;
          sendInput(event.data);
        }
      };
      helperTextarea?.addEventListener("compositionstart", handleCompositionStart);
      helperTextarea?.addEventListener("compositionend", handleCompositionEnd);

      ws.onopen = () => {
        term.writeln("[已连接] 终端已就绪");
        fitAddon.fit();
        emitResize();
        term.focus();
      };

      ws.onmessage = (event) => {
        if (typeof event.data === "string") {
          term.write(event.data);
        }
      };

      ws.onerror = () => {
        term.writeln("\r\n[错误] WebSocket 连接异常");
      };

      ws.onclose = () => {
        term.writeln("\r\n[连接关闭]");
      };

      term.attachCustomKeyEventHandler((event) => {
        if (event.type !== "keydown") {
          return true;
        }
        const sequence = mapKeyboardToAnsi(event);
        if (!sequence) {
          return true;
        }
        sendInput(sequence);
        event.preventDefault();
        return false;
      });

      const disposeData = term.onData((data) => {
        if (isComposing) {
          return;
        }

        if (imeEchoSuppression) {
          if (imeEchoSuppression.startsWith(data)) {
            imeEchoSuppression = imeEchoSuppression.slice(data.length);
            return;
          }

          if (data.startsWith(imeEchoSuppression)) {
            const remaining = data.slice(imeEchoSuppression.length);
            imeEchoSuppression = "";
            if (remaining) {
              sendInput(remaining);
            }
            return;
          }

          imeEchoSuppression = "";
        }

        sendInput(data);
      });

      const previousCleanup = () => {
        disposeData.dispose();
        resizeObserver.disconnect();
        helperTextarea?.removeEventListener("compositionstart", handleCompositionStart);
        helperTextarea?.removeEventListener("compositionend", handleCompositionEnd);
        window.removeEventListener("resize", handleResize);
      };

      (term as unknown as { __caoCleanup?: () => void }).__caoCleanup = previousCleanup;
    };

    void setupTerminal();

    return () => {
      disposed = true;
      const term = terminalRef.current as unknown as { __caoCleanup?: () => void } | null;
      term?.__caoCleanup?.();
      disconnectTerminal();
    };
  }, [disconnectTerminal, terminalId]);

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.45)",
        display: "flex",
        justifyContent: "flex-end",
        zIndex: 40,
      }}
      onClick={onClose}
    >
      <div
        onClick={(event) => event.stopPropagation()}
        style={{
          width: "80vw",
          minWidth: "min(640px, 100vw)",
          maxWidth: "100vw",
          height: "100%",
          background: "var(--surface)",
          borderLeft: "1px solid var(--border)",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
        }}
      >
        <div
          style={{
            padding: 14,
            borderBottom: "1px solid var(--border)",
            background: "var(--surface2)",
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: 10,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
            <div
              style={{
                width: 34,
                height: 34,
                borderRadius: "50%",
                border: "1px solid var(--border)",
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                fontWeight: 700,
                color: "var(--text-bright)",
                background: "var(--surface)",
                flexShrink: 0,
              }}
            >
              {title.slice(0, 1).toUpperCase()}
            </div>
            <div style={{ minWidth: 0 }}>
              <div
                style={{
                  color: "var(--text-bright)",
                  fontWeight: 700,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {title}
              </div>
              <div
                style={{
                  color: "var(--text-dim)",
                  fontSize: 12,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {subtitle}
              </div>
            </div>
          </div>
          <SecondaryButton type="button" onClick={onClose} style={{ padding: "6px 10px" }}>
            关闭
          </SecondaryButton>
        </div>

        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            minHeight: 0,
            background: "var(--surface)",
            padding: "10px 14px 14px",
          }}
        >
          <section
            style={{
              flex: 1,
              minHeight: 0,
              border: "1px solid var(--border)",
              borderRadius: 10,
              background: "var(--surface2)",
              overflow: "hidden",
              display: "flex",
              flexDirection: "column",
            }}
          >
            <div
              style={{
                padding: "8px 10px",
                borderBottom: "1px solid var(--border)",
                color: "var(--text-bright)",
                fontWeight: 700,
                fontSize: 13,
              }}
            >
              实时终端控制台
            </div>
            <div
              ref={terminalContainerRef}
              onMouseDown={() => terminalRef.current?.focus()}
              style={{
                flex: 1,
                minHeight: 0,
                width: "100%",
                overflow: "hidden",
                background: "#0d1117",
              }}
            />
          </section>
        </div>
      </div>
    </div>
  );
}
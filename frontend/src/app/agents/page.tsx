"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FitAddon } from "@xterm/addon-fit";
import type { Terminal as XTerm } from "@xterm/xterm";

import ConsoleNav from "@/components/ConsoleNav";
import {
  CardGrid,
  EmptyState,
  ErrorBanner,
  PageIntro,
  PageShell,
  SecondaryButton,
  SectionCard,
  StatCard,
  StatusPill,
} from "@/components/ConsoleTheme";
import RequireAuth from "@/components/RequireAuth";
import { caoRequest, ConsoleAgent, ConsoleOrganization, ConsoleTasksResponse } from "@/lib/cao";
import { isStatusActive, toStatusLabel } from "@/lib/status";

export default function AgentsPage() {
  const [organization, setOrganization] = useState<ConsoleOrganization | null>(null);
  const [error, setError] = useState("");
  const [activeAgent, setActiveAgent] = useState<ConsoleAgent | null>(null);
  const [taskTitleByAgent, setTaskTitleByAgent] = useState<Record<string, string>>({});

  const terminalContainerRef = useRef<HTMLDivElement | null>(null);
  const terminalRef = useRef<XTerm | null>(null);
  const fitAddonRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  const loadOrganization = useCallback(async () => {
    const [organizationResult, tasksResult] = await Promise.all([
      caoRequest<ConsoleOrganization>("GET", "/console/organization"),
      caoRequest<ConsoleTasksResponse>("GET", "/console/tasks"),
    ]);

    if (!organizationResult.ok) {
      setError("获取团队结构失败");
      return;
    }

    setOrganization(organizationResult.data);

    if (tasksResult.ok) {
      const nextTaskMap: Record<string, string> = {};
      for (const team of tasksResult.data.teams || []) {
        for (const instantTask of team.instant_tasks || []) {
          const terminalId = String(instantTask.terminal_id || "").trim();
          const taskTitle = String(instantTask.task_title || "").trim();
          if (terminalId && taskTitle) {
            nextTaskMap[terminalId] = taskTitle;
          }
        }
      }
      setTaskTitleByAgent(nextTaskMap);
    } else {
      setTaskTitleByAgent({});
    }

    setError("");
  }, []);

  useEffect(() => {
    const bootstrapTimer = setTimeout(() => {
      void loadOrganization();
    }, 0);
    const timer = setInterval(() => {
      void loadOrganization();
    }, 10000);
    return () => {
      clearInterval(timer);
      clearTimeout(bootstrapTimer);
    };
  }, [loadOrganization]);

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
    if (!activeAgent?.id || !terminalContainerRef.current) {
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
        fontFamily: "var(--mono)",
        fontSize: 13,
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
        process.env.NEXT_PUBLIC_CAO_CONTROL_PANEL_URL || "http://localhost:8000";
      const wsBase = controlPanelHttp.replace(/^http/i, "ws").replace(/\/$/, "");
      const wsUrl = `${wsBase}/console/agents/${activeAgent.id}/tmux/ws?token=${encodeURIComponent(
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
            "_": "\u001f",
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
  }, [activeAgent?.id, disconnectTerminal]);

  const leaderGroups = organization?.leader_groups || [];

  const agentsCount = useMemo(() => {
    if (!organization) {
      return 0;
    }
    return organization.leaders_total + organization.workers_total;
  }, [organization]);

  function closeAgentDrawer() {
    disconnectTerminal();
    setActiveAgent(null);
  }

  function openAgentDrawer(agent: ConsoleAgent) {
    setActiveAgent(agent);
  }

  return (
    <RequireAuth>
      <ConsoleNav />
      <PageShell>
        <PageIntro
          title="团队管理"
          description="以团队为单位查看在线情况，点击成员可打开实时控制台并直接执行终端命令。"
        />

        {error && <ErrorBanner text={error} />}

        <SectionCard style={{ padding: 10 }}>
          <CardGrid minWidth={180} gap={10}>
            <StatCard label="团队总数" value={organization?.leaders_total ?? 0} />
            <StatCard label="在岗员工总数" value={agentsCount} />
          </CardGrid>
        </SectionCard>

        {leaderGroups.length === 0 ? (
          <EmptyState text="暂无团队数据" />
        ) : (
          leaderGroups.map((group) => {
            const membersByProfile = group.members.reduce<Record<string, ConsoleAgent[]>>(
              (acc, member) => {
                const profile = member.agent_profile || "unknown";
                if (!acc[profile]) {
                  acc[profile] = [];
                }
                acc[profile].push(member);
                return acc;
              },
              {}
            );

            const memberProfileGroups = Object.entries(membersByProfile).sort(([a], [b]) =>
              a.localeCompare(b)
            );

            return (
              <SectionCard key={group.leader.id}>
                <div style={{ color: "var(--text-bright)", fontWeight: 700, marginBottom: 10 }}>
                  团队：{group.team_alias || group.leader.session_name || group.leader.id}
                </div>

                <div
                  onClick={() => openAgentDrawer(group.leader)}
                  style={{
                    border: "1px solid var(--border)",
                    borderRadius: 10,
                    padding: 10,
                    marginBottom: 12,
                    cursor: "pointer",
                    background: "var(--surface2)",
                  }}
                >
                  <div style={{ color: "var(--text-bright)", fontWeight: 700 }}>
                    负责人：{group.leader.alias || group.leader.id}
                  </div>
                  <div style={{ color: "var(--text-dim)", fontSize: 12 }}>
                    会话标题：{group.leader.session_name || "-"} · ID: {group.leader.id} · {group.leader.agent_profile} · {group.leader.provider}
                  </div>
                  <div style={{ display: "flex", marginTop: 6 }}>
                    <StatusPill
                      text={toStatusLabel(group.leader.status)}
                      active={isStatusActive(group.leader.status)}
                    />
                  </div>
                  {taskTitleByAgent[group.leader.id] && (
                    <div
                      title={taskTitleByAgent[group.leader.id]}
                      style={{
                        color: "var(--text-dim)",
                        fontSize: 12,
                        marginTop: 6,
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                      }}
                    >
                      当前任务：{taskTitleByAgent[group.leader.id]}
                    </div>
                  )}
                </div>

                {memberProfileGroups.length === 0 ? (
                  <EmptyState text="暂无团队成员" />
                ) : (
                  <div style={{ display: "grid", gap: 10 }}>
                    {memberProfileGroups.map(([profileName, members]) => (
                      <div
                        key={`${group.leader.id}-${profileName}`}
                        style={{
                          border: "1px solid var(--border)",
                          borderRadius: 10,
                          padding: 10,
                          background: "var(--surface2)",
                        }}
                      >
                        <div style={{ color: "var(--text-bright)", fontWeight: 700, marginBottom: 8 }}>
                          {profileName}（{members.length}）
                        </div>
                        <div
                          style={{
                            display: "grid",
                            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                            gap: 10,
                          }}
                        >
                          {members.map((member) => (
                            <div
                              key={member.id}
                              onClick={() => openAgentDrawer(member)}
                              style={{
                                border: "1px solid var(--border)",
                                borderRadius: 10,
                                padding: 10,
                                cursor: "pointer",
                                background: "var(--surface)",
                              }}
                            >
                              <div style={{ color: "var(--text-bright)", fontWeight: 700 }}>
                                {member.alias || member.id}
                              </div>
                              <div style={{ color: "var(--text-dim)", fontSize: 12 }}>
                                会话标题：{member.session_name || "-"} · ID: {member.id} · {member.provider}
                              </div>
                              <div style={{ display: "flex", marginTop: 6 }}>
                                <StatusPill
                                  text={toStatusLabel(member.status)}
                                  active={isStatusActive(member.status)}
                                />
                              </div>
                              {taskTitleByAgent[member.id] && (
                                <div
                                  title={taskTitleByAgent[member.id]}
                                  style={{
                                    color: "var(--text-dim)",
                                    fontSize: 12,
                                    marginTop: 6,
                                    whiteSpace: "nowrap",
                                    overflow: "hidden",
                                    textOverflow: "ellipsis",
                                  }}
                                >
                                  当前任务：{taskTitleByAgent[member.id]}
                                </div>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </SectionCard>
            );
          })
        )}

        {activeAgent && (
          <div
            style={{
              position: "fixed",
              inset: 0,
              background: "rgba(0,0,0,0.45)",
              display: "flex",
              justifyContent: "flex-end",
              zIndex: 40,
            }}
            onClick={closeAgentDrawer}
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
                    {(activeAgent.alias || activeAgent.id).slice(0, 1).toUpperCase()}
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
                      {activeAgent.alias || activeAgent.id}
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
                      {activeAgent.session_name || "-"} · {toStatusLabel(activeAgent.status)}
                    </div>
                  </div>
                </div>
                <SecondaryButton
                  type="button"
                  onClick={closeAgentDrawer}
                  style={{ padding: "6px 10px" }}
                >
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
        )}
      </PageShell>
    </RequireAuth>
  );
}

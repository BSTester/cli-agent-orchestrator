"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import ConsoleNav from "@/components/ConsoleNav";
import {
  CardGrid,
  EmptyState,
  ErrorBanner,
  PageIntro,
  PageShell,
  PrimaryButton,
  SecondaryButton,
  SectionCard,
  StatCard,
  StatusPill,
  TextAreaInput,
} from "@/components/ConsoleTheme";
import RequireAuth from "@/components/RequireAuth";
import { caoRequest, ConsoleAgent, ConsoleOrganization } from "@/lib/cao";
import { isStatusActive, toStatusLabel } from "@/lib/status";
import { summarizeTaskTitle } from "@/lib/taskTitle";

interface ChatItem {
  role: "user" | "assistant";
  content: string;
  at: number;
}

function formatChatTime(timestamp: number): string {
  return new Date(timestamp).toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function stripAnsi(input: string): string {
  return input.replace(/\u001b\[[0-9;]*m/g, "");
}

export default function AgentsPage() {
  const [organization, setOrganization] = useState<ConsoleOrganization | null>(null);
  const [error, setError] = useState("");

  const [activeAgent, setActiveAgent] = useState<ConsoleAgent | null>(null);
  const [chatItems, setChatItems] = useState<ChatItem[]>([]);
  const [chatItemsByAgent, setChatItemsByAgent] = useState<Record<string, ChatItem[]>>({});
  const [taskTitleByAgent, setTaskTitleByAgent] = useState<Record<string, string>>({});
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [currentOutput, setCurrentOutput] = useState("");
  const [streamTargetOutput, setStreamTargetOutput] = useState("");
  const [autoScroll, setAutoScroll] = useState(true);

  const chatRef = useRef<HTMLDivElement | null>(null);
  const messageFormRef = useRef<HTMLFormElement | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  const loadOrganization = useCallback(async () => {
    const result = await caoRequest<ConsoleOrganization>("GET", "/console/organization");
    if (!result.ok) {
      setError("获取团队结构失败");
      return;
    }
    setOrganization(result.data);
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

  useEffect(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    if (!activeAgent?.id) {
      return;
    }

    const eventSource = new EventSource(
      `/api/cao/console/agents/${activeAgent.id}/stream`,
      { withCredentials: true }
    );
    eventSourceRef.current = eventSource;

    eventSource.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as { output?: string };
        const outputText = String(payload.output || "").trim();
        if (!outputText) {
          return;
        }
        setStreamTargetOutput(outputText);
      } catch {
        // ignore malformed events
      }
    };

    eventSource.onerror = () => {
      eventSource.close();
      if (eventSourceRef.current === eventSource) {
        eventSourceRef.current = null;
      }
    };

    return () => {
      eventSource.close();
      if (eventSourceRef.current === eventSource) {
        eventSourceRef.current = null;
      }
    };
  }, [activeAgent?.id]);

  useEffect(() => {
    if (!streamTargetOutput) {
      return;
    }

    if (streamTargetOutput === currentOutput) {
      return;
    }

    if (!streamTargetOutput.startsWith(currentOutput)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCurrentOutput(streamTargetOutput);
      return;
    }

    const intervalId = window.setInterval(() => {
      setCurrentOutput((previous) => {
        if (previous === streamTargetOutput) {
          window.clearInterval(intervalId);
          return previous;
        }

        if (!streamTargetOutput.startsWith(previous)) {
          window.clearInterval(intervalId);
          return streamTargetOutput;
        }

        const remaining = streamTargetOutput.length - previous.length;
        const step = Math.max(1, Math.min(6, Math.ceil(remaining / 24)));
        const nextOutput = streamTargetOutput.slice(0, previous.length + step);

        if (nextOutput === streamTargetOutput) {
          window.clearInterval(intervalId);
        }

        return nextOutput;
      });
    }, 24);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [currentOutput, streamTargetOutput]);

  useEffect(() => {
    if (!currentOutput) {
      return;
    }

    // eslint-disable-next-line react-hooks/set-state-in-effect
    setChatItems((prev) => {
      if (prev.length === 0 || prev[prev.length - 1].role !== "assistant") {
        return [...prev, { role: "assistant", content: currentOutput, at: Date.now() }];
      }

      const lastItem = prev[prev.length - 1];
      if (lastItem.content === currentOutput) {
        return prev;
      }

      return [
        ...prev.slice(0, -1),
        {
          ...lastItem,
          content: currentOutput,
        },
      ];
    });
  }, [currentOutput]);

  useEffect(() => {
    if (!autoScroll || !chatRef.current) {
      return;
    }
    chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [chatItems, autoScroll]);

  useEffect(() => {
    if (!activeAgent?.id) {
      return;
    }
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setChatItemsByAgent((prev) => ({
      ...prev,
      [activeAgent.id]: chatItems,
    }));
  }, [activeAgent?.id, chatItems]);

  async function sendMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = message.trim();
    if (!activeAgent?.id || !text) {
      return;
    }

    setSending(true);
    const result = await caoRequest("POST", `/console/agents/${activeAgent.id}/input`, {
      body: { message: text },
    });

    if (!result.ok) {
      setError("发送消息失败");
      setSending(false);
      return;
    }

    setChatItems((prev) => [...prev, { role: "user", content: text, at: Date.now() }]);
    setTaskTitleByAgent((prev) => ({
      ...prev,
      [activeAgent.id]: summarizeTaskTitle(text),
    }));
    setMessage("");
    setSending(false);
  }

  const leaderGroups = organization?.leader_groups || [];

  const agentsCount = useMemo(() => {
    if (!organization) {
      return 0;
    }
    return organization.leaders_total + organization.workers_total;
  }, [organization]);

  function closeAgentChat() {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    setActiveAgent(null);
  }

  function openAgentChat(agent: ConsoleAgent) {
    const cachedItems = chatItemsByAgent[agent.id] || [];
    const latestAssistant = [...cachedItems].reverse().find((item) => item.role === "assistant");
    setActiveAgent(agent);
    setChatItems(cachedItems);
    setCurrentOutput(latestAssistant?.content || "");
    setStreamTargetOutput(latestAssistant?.content || "");
    setMessage("");
    setAutoScroll(true);
  }

  return (
    <RequireAuth>
      <ConsoleNav />
      <PageShell>
        <PageIntro
          title="团队管理"
          description="以团队为单位查看在线情况，点击任意成员卡片可进入会话与执行内容视图。"
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
            const membersByProfile = group.members.reduce<Record<string, ConsoleAgent[]>>((acc, member) => {
              const profile = member.agent_profile || "unknown";
              if (!acc[profile]) {
                acc[profile] = [];
              }
              acc[profile].push(member);
              return acc;
            }, {});

            const memberProfileGroups = Object.entries(membersByProfile).sort(([a], [b]) =>
              a.localeCompare(b)
            );

            return (
              <SectionCard key={group.leader.id}>
                <div style={{ color: "var(--text-bright)", fontWeight: 700, marginBottom: 10 }}>
                  团队：{group.team_alias || group.leader.session_name || group.leader.id}
                </div>

                <div
                  onClick={() => openAgentChat(group.leader)}
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
                    会话标题：{group.leader.session_name || "-"} · ID: {group.leader.id} · {group.leader.agent_profile} · {group.leader.provider} · {toStatusLabel(group.leader.status)}
                  </div>
                  <div style={{ display: "flex", marginTop: 6 }}>
                    <StatusPill
                      text={toStatusLabel(group.leader.status)}
                      active={isStatusActive(group.leader.status)}
                    />
                  </div>
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
                              onClick={() => openAgentChat(member)}
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
                              <div style={{ color: "var(--text-dim)", fontSize: 12 }}>
                                状态：{toStatusLabel(member.status)}
                              </div>
                              <div style={{ display: "flex", marginTop: 6 }}>
                                <StatusPill
                                  text={toStatusLabel(member.status)}
                                  active={isStatusActive(member.status)}
                                />
                              </div>
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
            onClick={closeAgentChat}
          >
            <div
              onClick={(e) => e.stopPropagation()}
              style={{
                width: "min(640px, 100%)",
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
                    <div style={{ color: "var(--text-bright)", fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {activeAgent.alias || activeAgent.id}
                    </div>
                    <div style={{ color: "var(--text-dim)", fontSize: 12, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {activeAgent.session_name || "-"} · {toStatusLabel(activeAgent.status)}
                    </div>
                  </div>
                </div>
                <SecondaryButton
                  type="button"
                  onClick={closeAgentChat}
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
                }}
              >
                {taskTitleByAgent[activeAgent.id] && (
                  <section
                    style={{
                      margin: "10px 14px",
                      border: "1px solid var(--border)",
                      borderRadius: 10,
                      background: "var(--surface2)",
                      padding: 10,
                    }}
                  >
                    <div style={{ color: "var(--text-dim)", fontSize: 12, marginBottom: 4 }}>
                      当前任务
                    </div>
                    <div style={{ color: "var(--text-bright)", fontWeight: 700, lineHeight: 1.45 }}>
                      {taskTitleByAgent[activeAgent.id]}
                    </div>
                  </section>
                )}

                <section
                  ref={chatRef}
                  className="console-chat-scroll"
                  style={{
                    flex: 1,
                    minHeight: 0,
                    overflow: "auto",
                    padding: taskTitleByAgent[activeAgent.id] ? "4px 14px 10px" : "10px 14px 10px",
                    display: "flex",
                    flexDirection: "column",
                    gap: 8,
                    background: "var(--surface)",
                  }}
                >
                  {chatItems.length === 0 ? (
                    <div
                      style={{
                        margin: "auto",
                        color: "var(--text-dim)",
                        border: "1px dashed var(--border)",
                        borderRadius: 10,
                        padding: "10px 12px",
                        background: "var(--surface2)",
                      }}
                    >
                      发送消息后开始会话
                    </div>
                  ) : (
                    chatItems.map((item) => {
                      const isUser = item.role === "user";
                      return (
                        <div
                          key={`${item.role}-${item.at}`}
                          style={{
                            display: "flex",
                            justifyContent: isUser ? "flex-end" : "flex-start",
                          }}
                        >
                          <div
                            style={{
                              maxWidth: "84%",
                              borderRadius: 12,
                              border: "1px solid var(--border)",
                              background: isUser ? "var(--accent)" : "var(--surface2)",
                              color: isUser ? "#fff" : "var(--text)",
                              padding: "8px 10px",
                              boxShadow: "0 1px 0 rgba(0,0,0,0.05)",
                            }}
                          >
                            <div
                              style={{
                                fontSize: 11,
                                marginBottom: 4,
                                color: isUser ? "rgba(255,255,255,0.9)" : "var(--text-dim)",
                              }}
                            >
                              {isUser ? "董事长" : "Agent"} · {formatChatTime(item.at)}
                            </div>
                            <div
                              className={isUser ? "chat-markdown chat-markdown-user" : "chat-markdown"}
                              style={{ fontSize: 13 }}
                            >
                              <ReactMarkdown
                                remarkPlugins={[remarkGfm]}
                                components={{
                                  a: ({ ...props }) => (
                                    <a
                                      {...props}
                                      target="_blank"
                                      rel="noreferrer"
                                      style={{
                                        color: isUser ? "#fff" : "var(--accent)",
                                        textDecoration: "underline",
                                      }}
                                    />
                                  ),
                                  code: ({ className, children, ...props }) => {
                                    const isBlock = Boolean(className);
                                    if (!isBlock) {
                                      return (
                                        <code
                                          {...props}
                                          style={{
                                            background: isUser ? "rgba(255,255,255,0.2)" : "var(--surface)",
                                            border: "1px solid var(--border)",
                                            borderRadius: 6,
                                            padding: "1px 4px",
                                            fontFamily: "var(--mono)",
                                            fontSize: 12,
                                          }}
                                        >
                                          {children}
                                        </code>
                                      );
                                    }
                                    return (
                                      <code
                                        className="chat-code-block"
                                        {...props}
                                        style={{
                                          display: "block",
                                          whiteSpace: "pre",
                                          overflowX: "auto",
                                          padding: 10,
                                          borderRadius: 8,
                                          border: "1px solid var(--border)",
                                          background: isUser ? "rgba(0,0,0,0.2)" : "var(--surface)",
                                          fontFamily: "var(--mono)",
                                          fontSize: 12,
                                        }}
                                      >
                                        {children}
                                      </code>
                                    );
                                  },
                                }}
                              >
                                {isUser ? item.content : stripAnsi(item.content)}
                              </ReactMarkdown>
                            </div>
                          </div>
                        </div>
                      );
                    })
                  )}
                </section>

                <form
                  ref={messageFormRef}
                  onSubmit={sendMessage}
                  style={{
                    borderTop: "1px solid var(--border)",
                    background: "var(--surface2)",
                    padding: 12,
                    display: "grid",
                    gap: 8,
                  }}
                >
                  <TextAreaInput
                    value={message}
                    onChange={(event) => setMessage(event.target.value)}
                    required
                    placeholder="输入指令并发送"
                    rows={4}
                    style={{
                      width: "100%",
                      minHeight: 96,
                      maxHeight: 180,
                      marginBottom: 0,
                      resize: "vertical",
                      lineHeight: 1.6,
                      fontSize: 14,
                    }}
                  />
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                    <div style={{ color: "var(--text-dim)", fontSize: 12 }}>
                      输入内容后点击“发送消息”
                    </div>
                    <SecondaryButton
                      type="button"
                      onClick={() => setMessage("")}
                      style={{ padding: "6px 10px" }}
                    >
                      清空输入
                    </SecondaryButton>
                    <PrimaryButton
                      type="submit"
                      disabled={sending}
                      style={{ minWidth: 108 }}
                    >
                      {sending ? "发送中..." : "发送消息"}
                    </PrimaryButton>
                  </div>
                </form>
              </div>
            </div>
            <style jsx global>{`
              .console-chat-scroll {
                scrollbar-color: var(--border) var(--surface2);
                scrollbar-width: thin;
              }
              .console-chat-scroll::-webkit-scrollbar {
                width: 10px;
                height: 10px;
              }
              .console-chat-scroll::-webkit-scrollbar-track {
                background: var(--surface2);
                border-radius: 999px;
              }
              .console-chat-scroll::-webkit-scrollbar-thumb {
                background: var(--border);
                border-radius: 999px;
                border: 2px solid var(--surface2);
              }
              .console-chat-scroll::-webkit-scrollbar-thumb:hover {
                background: var(--text-dim);
              }
              .chat-markdown p,
              .chat-markdown ul,
              .chat-markdown ol,
              .chat-markdown h1,
              .chat-markdown h2,
              .chat-markdown h3,
              .chat-markdown h4,
              .chat-markdown pre,
              .chat-markdown table,
              .chat-markdown blockquote {
                margin: 0 0 12px;
              }
              .chat-markdown p:last-child,
              .chat-markdown ul:last-child,
              .chat-markdown ol:last-child,
              .chat-markdown h1:last-child,
              .chat-markdown h2:last-child,
              .chat-markdown h3:last-child,
              .chat-markdown h4:last-child,
              .chat-markdown pre:last-child,
              .chat-markdown table:last-child,
              .chat-markdown blockquote:last-child {
                margin-bottom: 0;
              }
              .chat-markdown {
                line-height: 1.75;
                letter-spacing: 0.01em;
                font-size: 14px;
                word-break: break-word;
              }
              .chat-markdown h1,
              .chat-markdown h2,
              .chat-markdown h3,
              .chat-markdown h4 {
                line-height: 1.45;
                color: var(--text-bright);
                font-weight: 700;
              }
              .chat-markdown h1 {
                font-size: 1.2em;
              }
              .chat-markdown h2 {
                font-size: 1.12em;
              }
              .chat-markdown h3,
              .chat-markdown h4 {
                font-size: 1.04em;
              }
              .chat-markdown ul,
              .chat-markdown ol {
                padding-left: 20px;
              }
              .chat-markdown li + li {
                margin-top: 4px;
              }
              .chat-markdown table {
                width: 100%;
                border-collapse: collapse;
                font-size: 13px;
              }
              .chat-markdown th,
              .chat-markdown td {
                border: 1px solid var(--border);
                padding: 6px 8px;
              }
              .chat-markdown-user th,
              .chat-markdown-user td {
                border-color: rgba(255, 255, 255, 0.3);
              }
              .chat-markdown blockquote {
                border-left: 3px solid var(--border);
                padding-left: 10px;
                color: var(--text-dim);
              }
            `}</style>
          </div>
        )}
      </PageShell>
    </RequireAuth>
  );
}

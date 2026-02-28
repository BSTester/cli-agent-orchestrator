"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

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

interface ChatItem {
  role: "user" | "assistant";
  content: string;
  at: number;
}

type OutputMode = "stream" | "full";

function escapeHtml(input: string): string {
  return input
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function ansiToHtml(input: string): string {
  const colorMap: Record<string, string> = {
    "30": "#8b949e",
    "31": "#ff7b72",
    "32": "#3fb950",
    "33": "#d29922",
    "34": "#79c0ff",
    "35": "#bc8cff",
    "36": "#39c5cf",
    "37": "#c9d1d9",
    "90": "#6e7681",
    "91": "#ffa198",
    "92": "#56d364",
    "93": "#e3b341",
    "94": "#a5d6ff",
    "95": "#d2a8ff",
    "96": "#56d4dd",
    "97": "#f0f6fc",
  };

  let escaped = escapeHtml(input);
  escaped = escaped.replace(/\u001b\[0m/g, "</span>");
  escaped = escaped.replace(/\u001b\[([0-9]{2})m/g, (match, code: string) => {
    const color = colorMap[code];
    if (!color) {
      return "";
    }
    return `<span style=\"color:${color}\">`;
  });
  return escaped;
}

export default function AgentsPage() {
  const [organization, setOrganization] = useState<ConsoleOrganization | null>(null);
  const [error, setError] = useState("");

  const [activeAgent, setActiveAgent] = useState<ConsoleAgent | null>(null);
  const [chatItems, setChatItems] = useState<ChatItem[]>([]);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [currentOutput, setCurrentOutput] = useState("");
  const [outputMode, setOutputMode] = useState<OutputMode>("stream");
  const [autoScroll, setAutoScroll] = useState(true);

  const outputRef = useRef<HTMLDivElement | null>(null);
  const chatRef = useRef<HTMLDivElement | null>(null);

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
    if (!activeAgent?.id) {
      return;
    }

    if (outputMode !== "stream") {
      return;
    }

    const eventSource = new EventSource(
      `/api/cao/console/agents/${activeAgent.id}/stream`,
      { withCredentials: true }
    );

    eventSource.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data) as { output?: string };
        const outputText = String(payload.output || "").trim();
        if (!outputText) {
          return;
        }
        setCurrentOutput(outputText);
        setChatItems((prev) => {
          const hasSameLatest = prev.length > 0 && prev[prev.length - 1].content === outputText;
          if (hasSameLatest) {
            return prev;
          }
          return [...prev, { role: "assistant", content: outputText, at: Date.now() }];
        });
      } catch {
        // ignore malformed events
      }
    };

    eventSource.onerror = () => {
      eventSource.close();
    };

    return () => {
      eventSource.close();
    };
  }, [activeAgent?.id, outputMode]);

  useEffect(() => {
    if (!activeAgent?.id || outputMode !== "full") {
      return;
    }

    async function loadFullOutput() {
      const result = await caoRequest<{ output: string }>(
        "GET",
        `/terminals/${activeAgent.id}/output`,
        { query: { mode: "full" } }
      );
      if (!result.ok) {
        return;
      }
      const outputText = String(result.data.output || "");
      setCurrentOutput(outputText);
    }

    void loadFullOutput();
    const timer = setInterval(() => {
      void loadFullOutput();
    }, 3000);

    return () => clearInterval(timer);
  }, [activeAgent?.id, outputMode]);

  useEffect(() => {
    if (!autoScroll || !outputRef.current) {
      return;
    }
    outputRef.current.scrollTop = outputRef.current.scrollHeight;
  }, [currentOutput, autoScroll]);

  useEffect(() => {
    if (!autoScroll || !chatRef.current) {
      return;
    }
    chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [chatItems, autoScroll]);

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

  function openAgentChat(agent: ConsoleAgent) {
    setActiveAgent(agent);
    setChatItems([]);
    setCurrentOutput("");
    setMessage("");
    setOutputMode("stream");
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
            onClick={() => setActiveAgent(null)}
          >
            <div
              onClick={(e) => e.stopPropagation()}
              style={{
                width: "min(640px, 100%)",
                height: "100%",
                background: "var(--surface)",
                borderLeft: "1px solid var(--border)",
                padding: 14,
                overflow: "auto",
              }}
            >
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
                <div>
                  <div style={{ color: "var(--text-bright)", fontWeight: 700 }}>Agent 对话窗口</div>
                  <div style={{ color: "var(--text-dim)", fontSize: 12 }}>
                    {activeAgent.id} · 会话标题：{activeAgent.session_name || "-"} · {toStatusLabel(activeAgent.status)}
                  </div>
                </div>
                <SecondaryButton
                  type="button"
                  onClick={() => setActiveAgent(null)}
                  style={{ padding: "6px 10px" }}
                >
                  关闭
                </SecondaryButton>
              </div>

              <section style={{ marginBottom: 12, border: "1px solid var(--border)", borderRadius: 10, background: "var(--surface2)", padding: 10 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                  <div style={{ color: "var(--text-bright)", fontWeight: 700 }}>当前执行内容</div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <SecondaryButton
                      type="button"
                      onClick={() => setOutputMode((prev) => (prev === "stream" ? "full" : "stream"))}
                      style={{ padding: "4px 8px", fontSize: 12, background: "var(--surface)" }}
                    >
                      {outputMode === "stream" ? "切换全量日志" : "切换实时流"}
                    </SecondaryButton>
                    <SecondaryButton
                      type="button"
                      onClick={() => setAutoScroll((prev) => !prev)}
                      style={{ padding: "4px 8px", fontSize: 12, background: "var(--surface)" }}
                    >
                      {autoScroll ? "暂停自动滚动" : "开启自动滚动"}
                    </SecondaryButton>
                  </div>
                </div>
                <div
                  ref={outputRef}
                  style={{
                    maxHeight: 220,
                    overflow: "auto",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                    background: "#0d1117",
                    color: "#c9d1d9",
                    padding: 10,
                    fontSize: 12,
                    fontFamily: "var(--mono)",
                    whiteSpace: "pre-wrap",
                  }}
                  dangerouslySetInnerHTML={{
                    __html: ansiToHtml(currentOutput || "暂无输出"),
                  }}
                />
                <div style={{ color: "var(--text-dim)", fontSize: 11, marginTop: 6 }}>
                  模式：{outputMode === "stream" ? "实时流（SSE）" : "全量快照（3秒刷新）"}
                </div>
              </section>

              <section
                ref={chatRef}
                style={{
                  border: "1px solid var(--border)",
                  borderRadius: 10,
                  background: "var(--surface2)",
                  minHeight: 260,
                  maxHeight: 360,
                  overflow: "auto",
                  padding: 10,
                  marginBottom: 10,
                }}
              >
                {chatItems.length === 0 ? (
                  <div style={{ color: "var(--text-dim)" }}>发送消息后显示对话内容</div>
                ) : (
                  chatItems.map((item) => (
                    <div key={`${item.role}-${item.at}`} style={{ marginBottom: 8, border: "1px solid var(--border)", borderRadius: 8, padding: 8, background: item.role === "user" ? "#1b3a6a" : "var(--surface)" }}>
                      <div style={{ color: "var(--text-dim)", fontSize: 12, marginBottom: 4 }}>{item.role === "user" ? "董事长" : "Agent"}</div>
                      <div
                        style={{ whiteSpace: "pre-wrap", fontFamily: item.role === "assistant" ? "var(--mono)" : undefined }}
                        dangerouslySetInnerHTML={{
                          __html: item.role === "assistant" ? ansiToHtml(item.content) : escapeHtml(item.content),
                        }}
                      />
                    </div>
                  ))
                )}
              </section>

              <form onSubmit={sendMessage}>
                <TextAreaInput
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  required
                  placeholder="输入指令并发送"
                  style={{ width: "100%", minHeight: 90, marginBottom: 10 }}
                />
                <PrimaryButton
                  type="submit"
                  disabled={sending}
                >
                  {sending ? "发送中..." : "发送消息"}
                </PrimaryButton>
              </form>
            </div>
          </div>
        )}
      </PageShell>
    </RequireAuth>
  );
}

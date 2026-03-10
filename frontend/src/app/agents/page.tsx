"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

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
import TerminalDrawer from "@/components/TerminalDrawer";
import {
  caoRequest,
  ConsoleAgent,
  ConsoleEnsureOnlineResponse,
  ConsoleOrganization,
  ConsoleTasksResponse,
} from "@/lib/cao";
import { isStatusActive, toStatusLabel } from "@/lib/status";

export default function AgentsPage() {
  const [organization, setOrganization] = useState<ConsoleOrganization | null>(null);
  const [error, setError] = useState("");
  const [activeAgent, setActiveAgent] = useState<ConsoleAgent | null>(null);
  const [openingLeaderId, setOpeningLeaderId] = useState("");
  const [clockingOutLeaderId, setClockingOutLeaderId] = useState("");
  const [clockOutTarget, setClockOutTarget] = useState<{
    leaderId: string;
    teamName: string;
    sessionName: string;
    workerCount: number;
  } | null>(null);
  const [taskTitleByAgent, setTaskTitleByAgent] = useState<Record<string, string>>({});

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

  const leaderGroups = organization?.leader_groups || [];

  const agentsCount = useMemo(() => {
    if (!organization) {
      return 0;
    }
    return organization.leaders_total + organization.workers_total;
  }, [organization]);

  function extractErrorDetail(payload: unknown): string {
    if (!payload || typeof payload !== "object") {
      return "";
    }

    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === "string") {
      return detail;
    }
    if (detail && typeof detail === "object") {
      const nestedMessage = (detail as { message?: unknown }).message;
      if (typeof nestedMessage === "string") {
        return nestedMessage;
      }
      return JSON.stringify(detail);
    }

    const message = (payload as { message?: unknown }).message;
    if (typeof message === "string") {
      return message;
    }

    return "";
  }

  function closeAgentDrawer() {
    setActiveAgent(null);
  }

  function openAgentDrawer(agent: ConsoleAgent) {
    setActiveAgent(agent);
  }

  async function openLeaderDrawer(leader: ConsoleAgent) {
    const leaderId = String(leader.id || "").trim();
    if (!leaderId) {
      return;
    }

    setOpeningLeaderId(leaderId);
    setError("");

    const ensureResult = await caoRequest<ConsoleEnsureOnlineResponse>(
      "POST",
      `/console/organization/${encodeURIComponent(leaderId)}/ensure-online`
    );

    if (!ensureResult.ok || !ensureResult.data?.leader) {
      setError("恢复负责人会话失败");
      setOpeningLeaderId("");
      return;
    }

    setActiveAgent(ensureResult.data.leader);
    await loadOrganization();
    setOpeningLeaderId("");
  }

  function requestClockOut(group: (typeof leaderGroups)[number]) {
    const leaderId = String(group.leader.id || "").trim();
    if (!leaderId) {
      setError("下班失败：负责人ID为空");
      return;
    }

    setClockOutTarget({
      leaderId,
      teamName: String(group.team_alias || group.leader.session_name || group.leader.id || "-").trim(),
      sessionName: String(group.leader.session_name || "").trim(),
      workerCount: group.members.length,
    });
    setError("");
  }

  function cancelClockOut() {
    if (clockingOutLeaderId) {
      return;
    }
    setClockOutTarget(null);
  }

  async function confirmClockOut() {
    if (!clockOutTarget || clockingOutLeaderId) {
      return;
    }

    const currentTarget = clockOutTarget;
    setClockingOutLeaderId(currentTarget.leaderId);
    setError("");

    const result = await caoRequest<{ ok: boolean }>(
      "POST",
      `/console/organization/${encodeURIComponent(currentTarget.leaderId)}/clock-out`
    );

    if (!result.ok) {
      const detail = extractErrorDetail(result.data);
      setError(detail ? `下班失败：${detail}` : "下班失败");
      setClockingOutLeaderId("");
      return;
    }

    if (activeAgent?.id && activeAgent.id === currentTarget.leaderId) {
      closeAgentDrawer();
    }

    setClockOutTarget(null);
    await loadOrganization();
    setClockingOutLeaderId("");
  }

  return (
    <RequireAuth>
      <ConsoleNav />
      <PageShell>
        <PageIntro
          title="会话管理"
          description="以会话为单位查看在线情况，点击成员可打开实时控制台并直接执行终端命令。"
        />

        {error && <ErrorBanner text={error} />}

        <SectionCard style={{ padding: 10 }}>
          <CardGrid minWidth={180} gap={10}>
            <StatCard label="会话总数" value={organization?.leaders_total ?? 0} />
            <StatCard label="在岗员工总数" value={agentsCount} />
          </CardGrid>
        </SectionCard>

        {leaderGroups.length === 0 ? (
          <EmptyState text="暂无会话数据" />
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
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    gap: 8,
                    marginBottom: 10,
                  }}
                >
                  <div style={{ color: "var(--text-bright)", fontWeight: 700 }}>
                    会话：{group.team_alias || group.leader.session_name || group.leader.id}
                  </div>
                  <SecondaryButton
                    type="button"
                    onClick={() => requestClockOut(group)}
                    style={{ padding: "4px 8px", fontSize: 12 }}
                    disabled={
                      Boolean(openingLeaderId) ||
                      Boolean(clockingOutLeaderId)
                    }
                  >
                    {clockingOutLeaderId === group.leader.id ? "下班中..." : "下班"}
                  </SecondaryButton>
                </div>

                <div
                  onClick={() => {
                    if (openingLeaderId) {
                      return;
                    }
                    void openLeaderDrawer(group.leader);
                  }}
                  style={{
                    border: "1px solid var(--border)",
                    borderRadius: 10,
                    padding: 10,
                    marginBottom: 12,
                    cursor: openingLeaderId ? "wait" : "pointer",
                    background: "var(--surface2)",
                    opacity: openingLeaderId && openingLeaderId === group.leader.id ? 0.75 : 1,
                  }}
                >
                  <div style={{ color: "var(--text-bright)", fontWeight: 700 }}>
                    负责人：{group.leader.alias || group.leader.id}
                  </div>
                  <div style={{ color: "var(--text-dim)", fontSize: 12 }}>
                    会话标题：{group.leader.session_name || "-"} · ID: {group.leader.id} · {group.leader.agent_profile} · {group.leader.provider}
                  </div>
                  {openingLeaderId === group.leader.id ? (
                    <div style={{ color: "var(--text-dim)", fontSize: 12, marginTop: 6 }}>
                      正在恢复负责人会话...
                    </div>
                  ) : null}
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
                  <EmptyState text="暂无会话成员" />
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

        {activeAgent?.id ? (
          <TerminalDrawer
            terminalId={activeAgent.id}
            title={activeAgent.alias || activeAgent.id}
            subtitle={`${activeAgent.session_name || "-"} · ${toStatusLabel(activeAgent.status)}`}
            onClose={closeAgentDrawer}
          />
        ) : null}

        {clockOutTarget && (
          <div
            style={{
              position: "fixed",
              inset: 0,
              zIndex: 41,
              background: "rgba(0,0,0,0.45)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: 16,
            }}
            onClick={cancelClockOut}
          >
            <div
              role="dialog"
              aria-modal="true"
              aria-label="下班确认"
              onClick={(event) => event.stopPropagation()}
              style={{
                width: "min(560px, 100%)",
                background: "var(--surface)",
                border: "1px solid var(--border)",
                borderRadius: 12,
                padding: 14,
              }}
            >
              <div style={{ color: "var(--text-bright)", fontWeight: 700, marginBottom: 8 }}>
                确认团队下班
              </div>
              <div style={{ color: "var(--text-dim)", fontSize: 13, marginBottom: 4 }}>
                会话：{clockOutTarget.teamName}
              </div>
              <div style={{ color: "var(--text-dim)", fontSize: 13, marginBottom: 4 }}>
                负责人：{clockOutTarget.leaderId}
              </div>
              <div style={{ color: "var(--text-dim)", fontSize: 13, marginBottom: 12 }}>
                Worker 数：{clockOutTarget.workerCount}
              </div>
              <div style={{ color: "var(--text-dim)", fontSize: 12, marginBottom: 14 }}>
                确认后将退出全部 Worker 终端，并退出负责人终端（保留会话）；负责人状态将变为下线。
              </div>
              <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
                <SecondaryButton type="button" onClick={cancelClockOut} disabled={Boolean(clockingOutLeaderId)}>
                  取消
                </SecondaryButton>
                <SecondaryButton
                  type="button"
                  onClick={() => void confirmClockOut()}
                  disabled={Boolean(clockingOutLeaderId)}
                >
                  {clockingOutLeaderId ? "处理中..." : "确认下班"}
                </SecondaryButton>
              </div>
            </div>
          </div>
        )}
      </PageShell>
    </RequireAuth>
  );
}

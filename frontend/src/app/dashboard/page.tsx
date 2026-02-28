"use client";

import { useEffect, useMemo, useState } from "react";

import ConsoleNav from "@/components/ConsoleNav";
import { CardGrid, EmptyState, ErrorBanner, PageIntro, PageShell, SectionCard, SectionTitle, StatCard } from "@/components/ConsoleTheme";
import RequireAuth from "@/components/RequireAuth";
import { caoRequest, ConsoleAgent, ConsoleOverview, ConsoleTasksResponse } from "@/lib/cao";
import { toStatusLabel } from "@/lib/status";

function BarChartCard({
  title,
  rows,
}: {
  title: string;
  rows: Array<{ label: string; value: number }>;
}) {
  const total = rows.reduce((sum, row) => sum + row.value, 0);
  const palette = [
    "#60a5fa",
    "#34d399",
    "#f59e0b",
    "#f472b6",
    "#a78bfa",
    "#22d3ee",
    "#f87171",
    "#84cc16",
  ];

  const normalizedRows = rows.filter((row) => row.value > 0).sort((a, b) => b.value - a.value);
  const maxValue = normalizedRows.reduce((max, row) => Math.max(max, row.value), 0);

  return (
    <div
      style={{
        background: "var(--surface)",
        border: "1px solid var(--border)",
        borderRadius: 12,
        padding: 14,
      }}
    >
      <div style={{ color: "var(--text-bright)", fontWeight: 700, marginBottom: 10 }}>{title}</div>
      {normalizedRows.length === 0 ? (
        <EmptyState text="暂无数据" />
      ) : (
        <div
          style={{
            border: "1px solid var(--border)",
            borderRadius: 10,
            background: "var(--surface2)",
            padding: "10px 8px 8px",
            overflowX: "auto",
          }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "flex-end",
              gap: 10,
              minHeight: 210,
              minWidth: Math.max(280, normalizedRows.length * 70),
            }}
          >
          {normalizedRows.map((row, index) => {
            const percent = total > 0 ? Math.round((row.value / total) * 100) : 0;
            const barHeight = maxValue > 0 ? Math.max(8, (row.value / maxValue) * 150) : 0;
            return (
              <div
                key={row.label}
                style={{
                  width: 60,
                  display: "grid",
                  justifyItems: "center",
                  gap: 6,
                }}
              >
                <div
                  style={{
                    color: "var(--text-dim)",
                    fontSize: 11,
                    textAlign: "center",
                  }}
                >
                  {row.value}
                </div>
                <div
                  title={`${row.label}: ${row.value} (${percent}%)`}
                  style={{
                    width: 26,
                    height: 160,
                    display: "flex",
                    alignItems: "flex-end",
                    background: "var(--surface)",
                    border: "1px solid var(--border)",
                    borderRadius: 8,
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      width: "100%",
                      height: barHeight,
                      background: palette[index % palette.length],
                    }}
                  />
                </div>
                <div
                  style={{
                    color: "var(--text)",
                    fontSize: 11,
                    textAlign: "center",
                    lineHeight: 1.2,
                    wordBreak: "break-word",
                  }}
                >
                  {row.label}
                </div>
                <div style={{ color: "var(--text-dim)", fontSize: 10 }}>{percent}%</div>
              </div>
            );
          })}
          </div>
        </div>
      )}
    </div>
  );
}

function formatUptime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return `${h}h ${m}m ${s}s`;
}

export default function DashboardPage() {
  const [overview, setOverview] = useState<ConsoleOverview | null>(null);
  const [tasksOverview, setTasksOverview] = useState<ConsoleTasksResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let canceled = false;

    async function fetchOverview() {
      const [overviewResult, tasksResult] = await Promise.all([
        caoRequest<ConsoleOverview>("GET", "/console/overview"),
        caoRequest<ConsoleTasksResponse>("GET", "/console/tasks"),
      ]);

      if (canceled) {
        return;
      }

      if (!overviewResult.ok) {
        setError("获取控制台统计失败");
        return;
      }

      setOverview(overviewResult.data);
      if (tasksResult.ok) {
        setTasksOverview(tasksResult.data);
      } else {
        setTasksOverview(null);
      }
      setError("");
    }

    fetchOverview();
    const timer = setInterval(fetchOverview, 10000);
    return () => {
      canceled = true;
      clearInterval(timer);
    };
  }, []);

  const providerRows = Object.entries(overview?.provider_counts || {});
  const statusRows = Object.entries(overview?.status_counts || {});
  const mainAgents: ConsoleAgent[] = useMemo(() => overview?.main_agents || [], [overview?.main_agents]);
  const mainStatusRows = useMemo(() => {
    const counts = new Map<string, number>();
    mainAgents.forEach((agent) => {
      const key = agent.status || "unknown";
      counts.set(key, (counts.get(key) || 0) + 1);
    });
    return Array.from(counts.entries()).map(([label, value]) => ({
      label: toStatusLabel(label),
      value,
    }));
  }, [mainAgents]);

  const leaderTaskRows = useMemo(() => {
    const teams = tasksOverview?.teams || [];
    return teams
      .map((team) => {
        const taskCount = team.instant_tasks.length + team.scheduled_tasks.length;
        return {
          label: team.leader.alias || team.leader.session_name || team.leader.id,
          value: taskCount,
        };
      })
      .filter((row) => row.value > 0)
      .sort((a, b) => b.value - a.value);
  }, [tasksOverview?.teams]);

  return (
    <RequireAuth>
      <ConsoleNav />
      <PageShell>
        <PageIntro
          title="集团总览"
          description="首页仅展示集团统计与健康态势，组织与任务操作请前往对应页面。"
        />
        {error && <ErrorBanner text={error} />}

        <SectionTitle title="核心指标" />
        <SectionCard
          style={{
            padding: 10,
          }}
        >
          <CardGrid minWidth={180} gap={12}>
            <StatCard label="集团在岗员工" value={overview?.agents_total ?? "-"} />
            <StatCard label="在营团队数" value={overview?.main_agents_total ?? "-"} />
            <StatCard label="团队成员数" value={overview?.worker_agents_total ?? "-"} />
            <StatCard label="集团系统运行时长" value={overview ? formatUptime(overview.uptime_seconds) : "-"} />
          </CardGrid>
        </SectionCard>

        <SectionTitle title="运行分布" />
        <CardGrid minWidth={360} gap={12}>
          <BarChartCard
            title="Provider类型分布图"
            rows={providerRows.map(([label, value]) => ({ label, value }))}
          />
          <BarChartCard
            title="运行状态分布图"
            rows={statusRows.map(([label, value]) => ({ label: toStatusLabel(label), value }))}
          />
        </CardGrid>

        <SectionCard>
          <div style={{ color: "var(--text-bright)", fontWeight: 700, marginBottom: 8 }}>团队负责人看板</div>
          <CardGrid minWidth={320} gap={12}>
            {mainStatusRows.length > 0 && (
              <BarChartCard title="负责人状态分布" rows={mainStatusRows} />
            )}
            <BarChartCard title="负责人团队任务数" rows={leaderTaskRows} />
          </CardGrid>
          {mainAgents.length === 0 ? (
            <EmptyState text="当前没有在营团队" />
          ) : (
            mainAgents.map((agent) => (
              <div
                key={agent.id}
                style={{
                  padding: "8px 10px",
                  border: "1px solid var(--border)",
                  borderRadius: 10,
                  marginBottom: 8,
                  background: "var(--surface2)",
                }}
              >
                <div style={{ color: "var(--text-bright)", fontFamily: "var(--mono)", fontSize: 12 }}>{agent.id}</div>
                <div style={{ color: "var(--text-dim)", fontSize: 12 }}>
                  会话标题：{agent.session_name || "-"} · {agent.agent_profile} · {agent.provider} · {toStatusLabel(agent.status)}
                </div>
              </div>
            ))
          )}
        </SectionCard>
      </PageShell>
    </RequireAuth>
  );
}

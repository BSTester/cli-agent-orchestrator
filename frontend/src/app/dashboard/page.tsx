"use client";

import { useEffect, useMemo, useState } from "react";

import ConsoleNav from "@/components/ConsoleNav";
import { CardGrid, EmptyState, ErrorBanner, PageIntro, PageShell, SectionCard, SectionTitle, StatCard } from "@/components/ConsoleTheme";
import RequireAuth from "@/components/RequireAuth";
import { caoRequest, ConsoleAgent, ConsoleOverview } from "@/lib/cao";
import { toStatusLabel } from "@/lib/status";

function PieChartCard({
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

  const normalizedRows = rows.filter((row) => row.value > 0);
  let current = 0;
  const gradientStops = normalizedRows
    .map((row, index) => {
      const start = current;
      const degree = total > 0 ? (row.value / total) * 360 : 0;
      const end = start + degree;
      current = end;
      return `${palette[index % palette.length]} ${start}deg ${end}deg`;
    })
    .join(", ");

  const chartBackground = gradientStops
    ? `conic-gradient(${gradientStops})`
    : "var(--surface2)";

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
        <div style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: 12, alignItems: "center" }}>
          <div
            style={{
              width: 140,
              height: 140,
              borderRadius: "50%",
              background: chartBackground,
              border: "1px solid var(--border)",
              margin: "0 auto",
            }}
          />
          <div>
            {normalizedRows.map((row, index) => {
              const percent = total > 0 ? Math.round((row.value / total) * 100) : 0;
              return (
                <div key={row.label} style={{ display: "flex", justifyContent: "space-between", marginBottom: 8, gap: 8 }}>
                  <span style={{ color: "var(--text)", fontSize: 13, display: "inline-flex", alignItems: "center", gap: 6 }}>
                    <span
                      style={{
                        display: "inline-block",
                        width: 10,
                        height: 10,
                        borderRadius: 999,
                        background: palette[index % palette.length],
                      }}
                    />
                    {row.label}
                  </span>
                  <span style={{ color: "var(--text-dim)", fontSize: 12 }}>
                    {row.value} ({percent}%)
                  </span>
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
  const [error, setError] = useState("");

  useEffect(() => {
    let canceled = false;

    async function fetchOverview() {
      const result = await caoRequest<ConsoleOverview>("GET", "/console/overview");
      if (canceled) {
        return;
      }
      if (!result.ok) {
        setError("获取控制台统计失败");
        return;
      }
      setOverview(result.data);
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
  const mainAgents: ConsoleAgent[] = overview?.main_agents || [];
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
        <CardGrid minWidth={260} gap={12}>
          <PieChartCard
            title="Provider类型分布图"
            rows={providerRows.map(([label, value]) => ({ label, value }))}
          />
          <PieChartCard
            title="运行状态分布图"
            rows={statusRows.map(([label, value]) => ({ label: toStatusLabel(label), value }))}
          />
        </CardGrid>

        <SectionCard>
          <div style={{ color: "var(--text-bright)", fontWeight: 700, marginBottom: 8 }}>团队负责人看板</div>
          {mainStatusRows.length > 0 && (
            <div style={{ marginBottom: 12 }}>
              <PieChartCard title="负责人状态分布" rows={mainStatusRows} />
            </div>
          )}
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

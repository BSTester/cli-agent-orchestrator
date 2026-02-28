"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import ConsoleNav from "@/components/ConsoleNav";
import {
  CardGrid,
  CodeEditorInput,
  EmptyState,
  ErrorBanner,
  PageIntro,
  PageShell,
  PrimaryButton,
  SectionCard,
  SectionTitle,
  SecondaryButton,
  SelectInput,
  StatCard,
  StatusPill,
  TextInput,
} from "@/components/ConsoleTheme";
import RequireAuth from "@/components/RequireAuth";
import {
  caoRequest,
  ConsoleScheduledTaskFile,
  ConsoleScheduledTaskFilesResponse,
  ConsoleTasksResponse,
} from "@/lib/cao";
import { isStatusActive, toStatusLabel } from "@/lib/status";

export default function TasksPage() {
  const [data, setData] = useState<ConsoleTasksResponse | null>(null);
  const [flowFiles, setFlowFiles] = useState<ConsoleScheduledTaskFilesResponse["files"]>([]);
  const [error, setError] = useState("");

  const [creating, setCreating] = useState(false);
  const [loadingFileContent, setLoadingFileContent] = useState(false);

  const [flowName, setFlowName] = useState("");
  const [flowContent, setFlowContent] = useState(`---
name: morning-trivia
schedule: "30 7 * * *"
agent_profile: developer
provider: kiro_cli
---

Share one interesting world trivia for today.
`);
  const [leaderId, setLeaderId] = useState("");

  const [selectedFileName, setSelectedFileName] = useState("");

  const loadTasks = useCallback(async () => {
    const result = await caoRequest<ConsoleTasksResponse>("GET", "/console/tasks");
    if (!result.ok) {
      setError("获取任务数据失败");
      return;
    }
    setData(result.data);
    setError("");
  }, []);

  const loadFlowFiles = useCallback(async () => {
    const result = await caoRequest<ConsoleScheduledTaskFilesResponse>(
      "GET",
      "/console/tasks/scheduled/files"
    );
    if (!result.ok) {
      return;
    }
    setFlowFiles(result.data.files || []);
  }, []);

  useEffect(() => {
    const bootstrapTimer = setTimeout(() => {
      void loadTasks();
      void loadFlowFiles();
    }, 0);

    const timer = setInterval(() => {
      void loadTasks();
    }, 10000);

    return () => {
      clearInterval(timer);
      clearTimeout(bootstrapTimer);
    };
  }, [loadFlowFiles, loadTasks]);

  async function createScheduledTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!flowContent.trim()) {
      return;
    }

    setCreating(true);

    const result = await caoRequest("POST", "/console/tasks/scheduled", {
      body: {
        file_name: selectedFileName.trim() || undefined,
        flow_name: selectedFileName.trim() ? undefined : flowName.trim() || undefined,
        flow_content: flowContent.trim(),
        leader_id: leaderId.trim() || undefined,
      },
    });

    if (!result.ok) {
      setError("创建定时任务失败");
      setCreating(false);
      return;
    }

    setFlowName("");
    setCreating(false);
    await loadFlowFiles();
    await loadTasks();
  }

  async function onSelectFlowFile(fileName: string) {
    setSelectedFileName(fileName);
    if (!fileName) {
      return;
    }

    setLoadingFileContent(true);
    const result = await caoRequest<ConsoleScheduledTaskFile & { content: string }>(
      "GET",
      `/console/tasks/scheduled/files/${encodeURIComponent(fileName)}`
    );

    if (!result.ok) {
      setError("读取任务文件失败");
      setLoadingFileContent(false);
      return;
    }

    setFlowName(result.data.flow_name || "");
    setFlowContent(result.data.content || "");
    setLoadingFileContent(false);
  }

  async function runScheduledTask(name: string) {
    const result = await caoRequest("POST", `/console/tasks/scheduled/${name}/run`);
    if (!result.ok) {
      setError("触发定时任务失败");
      return;
    }
    await loadTasks();
  }

  async function toggleScheduledTask(name: string, enabled: boolean) {
    const action = enabled ? "disable" : "enable";
    const result = await caoRequest("POST", `/console/tasks/scheduled/${name}/${action}`);
    if (!result.ok) {
      setError(enabled ? "暂停任务失败" : "启用任务失败");
      return;
    }
    await loadTasks();
  }

  async function deleteScheduledTask(name: string) {
    const result = await caoRequest("DELETE", `/console/tasks/scheduled/${name}`);
    if (!result.ok) {
      setError("删除任务失败");
      return;
    }
    await loadTasks();
  }

  const teams = data?.teams || [];
  const teamCount = teams.length;
  const instantTaskCount = teams.reduce((sum, team) => sum + team.instant_tasks.length, 0);
  const scheduledTaskCount =
    teams.reduce((sum, team) => sum + team.scheduled_tasks.length, 0) +
    (data?.unassigned_scheduled_tasks.length || 0);

  return (
    <RequireAuth>
      <ConsoleNav />
      <PageShell>
        <PageIntro
          title="任务管理"
          description="以团队为单位查看即时任务与定时任务，并支持手动发起定时任务。"
        />

        {error && <ErrorBanner text={error} />}

        <SectionCard style={{ padding: 10 }}>
          <CardGrid minWidth={180} gap={10}>
            <StatCard label="团队数" value={teamCount} />
            <StatCard label="即时任务" value={instantTaskCount} />
            <StatCard label="定时任务" value={scheduledTaskCount} />
          </CardGrid>
        </SectionCard>

        <SectionCard>
          <SectionTitle title="新建/编辑定时任务" />
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))",
              gap: 10,
              alignItems: "stretch",
              marginBottom: 12,
            }}
          >
            <SelectInput
              value={selectedFileName}
              onChange={(event) => void onSelectFlowFile(event.target.value)}
              disabled={loadingFileContent}
            >
              <option value="">选择已有文件并加载到编辑器（可选）</option>
              {flowFiles.map((fileItem) => (
                <option key={fileItem.file_name} value={fileItem.file_name}>
                  {fileItem.file_name}
                </option>
              ))}
            </SelectInput>
            <SelectInput
              value={leaderId}
              onChange={(event) => setLeaderId(event.target.value)}
            >
              <option value="">不绑定团队</option>
              {teams.map((team) => (
                <option key={`leader-${team.leader.id}`} value={team.leader.id}>
                  {team.leader.session_name || team.leader.id}
                </option>
              ))}
            </SelectInput>
          </div>

          <div style={{ color: "var(--text-dim)", fontSize: 12, marginBottom: 10 }}>
            {loadingFileContent
              ? "任务文件加载中..."
              : "选择已有文件后会回填到编辑器；提交时将保存到原文件并发起任务。未选择文件时将按名称创建新文件。"}
          </div>
          <form
            onSubmit={createScheduledTask}
            style={{
              display: "grid",
              gap: 10,
              alignItems: "stretch",
            }}
          >
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
                gap: 10,
              }}
            >
              <TextInput
                value={flowName}
                onChange={(event) => setFlowName(event.target.value)}
                placeholder="Flow 名称（新建时可选，编辑已有文件时将自动带出）"
              />
            </div>
            <CodeEditorInput
              value={flowContent}
              onChange={setFlowContent}
              language="auto"
              fileName={selectedFileName || flowName}
              showToolbar
              enableFormat
              required
              placeholder="请输入完整 flow markdown（含 frontmatter）"
              style={{ width: "100%", minHeight: 220 }}
            />
            <PrimaryButton
              type="submit"
              disabled={creating}
              style={{ minHeight: 38, width: "fit-content", justifySelf: "start", padding: "8px 16px" }}
            >
              {creating
                ? "提交中..."
                : selectedFileName
                  ? "保存并发起任务"
                  : "创建并发起任务"}
            </PrimaryButton>
          </form>
        </SectionCard>

        {teams.length === 0 ? (
          <EmptyState text="暂无团队任务数据" />
        ) : (
          teams.map((team) => (
            <SectionCard key={team.leader.id}>
              <div style={{ color: "var(--text-bright)", fontWeight: 700, marginBottom: 10 }}>
                团队：{team.leader.session_name || team.leader.id}
              </div>
              <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
                <StatusPill text={`即时 ${team.instant_tasks.length}`} active={team.instant_tasks.length > 0} />
                <StatusPill text={`定时 ${team.scheduled_tasks.length}`} active={team.scheduled_tasks.length > 0} />
              </div>

              <CardGrid minWidth={260} gap={10}>
                <div
                  style={{
                    border: "1px solid var(--border)",
                    borderRadius: 10,
                    padding: 10,
                    background: "var(--surface2)",
                    minHeight: 220,
                  }}
                >
                  <div style={{ color: "var(--text-bright)", fontWeight: 700, marginBottom: 8 }}>
                    即时任务
                  </div>
                  {team.instant_tasks.length === 0 ? (
                    <div style={{ color: "var(--text-dim)", fontSize: 13 }}>当前无执行中的即时任务</div>
                  ) : (
                    team.instant_tasks.map((task) => (
                      <div
                        key={task.terminal_id}
                        style={{
                          border: "1px solid var(--border)",
                          borderRadius: 8,
                          padding: 8,
                          marginBottom: 8,
                          background: "var(--surface)",
                        }}
                      >
                        <div style={{ color: "var(--text-bright)", fontWeight: 700 }}>{task.terminal_id}</div>
                        <div style={{ color: "var(--text-dim)", fontSize: 12, marginBottom: 4 }}>
                          {task.agent_profile || "unknown"}
                        </div>
                        <div style={{ display: "flex" }}>
                          <StatusPill
                            text={toStatusLabel(task.status || "unknown")}
                            active={isStatusActive(task.status)}
                          />
                        </div>
                      </div>
                    ))
                  )}
                </div>

                <div
                  style={{
                    border: "1px solid var(--border)",
                    borderRadius: 10,
                    padding: 10,
                    background: "var(--surface2)",
                    minHeight: 220,
                  }}
                >
                  <div style={{ color: "var(--text-bright)", fontWeight: 700, marginBottom: 8 }}>
                    定时任务
                  </div>
                  {team.scheduled_tasks.length === 0 ? (
                    <div style={{ color: "var(--text-dim)", fontSize: 13 }}>当前无定时任务</div>
                  ) : (
                    team.scheduled_tasks.map((task) => (
                      <div
                        key={task.name}
                        style={{
                          border: "1px solid var(--border)",
                          borderRadius: 8,
                          padding: 8,
                          marginBottom: 8,
                          background: "var(--surface)",
                        }}
                      >
                        <div style={{ color: "var(--text-bright)", fontWeight: 700 }}>{task.name}</div>
                        <div style={{ color: "var(--text-dim)", fontSize: 12, marginTop: 2, marginBottom: 8 }}>
                          {task.schedule} · {task.agent_profile}
                        </div>
                        <div style={{ display: "flex", marginBottom: 8 }}>
                          <StatusPill text={task.enabled ? "已启用" : "已暂停"} active={task.enabled} />
                        </div>
                        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                          <SecondaryButton
                            type="button"
                            onClick={() => runScheduledTask(task.name)}
                            style={{ padding: "4px 8px", fontSize: 12 }}
                          >
                            手动触发
                          </SecondaryButton>
                          <SecondaryButton
                            type="button"
                            onClick={() => toggleScheduledTask(task.name, task.enabled)}
                            style={{ padding: "4px 8px", fontSize: 12 }}
                          >
                            {task.enabled ? "暂停" : "启用"}
                          </SecondaryButton>
                          <SecondaryButton
                            type="button"
                            onClick={() => deleteScheduledTask(task.name)}
                            style={{ padding: "4px 8px", fontSize: 12 }}
                          >
                            删除
                          </SecondaryButton>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </CardGrid>
            </SectionCard>
          ))
        )}

        {!!data?.unassigned_scheduled_tasks?.length && (
          <SectionCard>
            <div style={{ color: "var(--text-bright)", fontWeight: 700, marginBottom: 10 }}>
              未绑定团队的定时任务
            </div>
            {data.unassigned_scheduled_tasks.map((task) => (
              <div
                key={task.name}
                style={{
                  border: "1px solid var(--border)",
                  borderRadius: 8,
                  padding: 8,
                  marginBottom: 8,
                  background: "var(--surface2)",
                }}
              >
                <div style={{ color: "var(--text-bright)", fontWeight: 700 }}>{task.name}</div>
                <div style={{ color: "var(--text-dim)", fontSize: 12, marginTop: 2 }}>
                  {task.schedule} · {task.agent_profile}
                </div>
                <div style={{ display: "flex", marginTop: 6 }}>
                  <StatusPill text={task.enabled ? "已启用" : "已暂停"} active={task.enabled} />
                </div>
              </div>
            ))}
          </SectionCard>
        )}
      </PageShell>
    </RequireAuth>
  );
}

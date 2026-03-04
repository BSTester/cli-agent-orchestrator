"use client";

import { FormEvent, InputHTMLAttributes, useCallback, useEffect, useState } from "react";

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

function SearchableDatalistInput(
  props: InputHTMLAttributes<HTMLInputElement> & { onClear?: () => void }
) {
  const { onClear, value, style, className, ...rest } = props;
  const hasValue = String(value ?? "").length > 0;

  return (
    <div style={{ position: "relative", width: "100%" }}>
      <TextInput
        {...rest}
        className={["cao-searchable-datalist", className].filter(Boolean).join(" ")}
        value={value}
        style={{ width: "100%", ...(style || {}), paddingRight: 28 }}
      />
      {hasValue ? (
        <button
          type="button"
          aria-label="清空"
          onClick={onClear}
          style={{
            position: "absolute",
            right: 8,
            top: "50%",
            transform: "translateY(-50%)",
            border: "none",
            background: "transparent",
            color: "var(--text-dim)",
            cursor: "pointer",
            fontSize: 14,
            lineHeight: 1,
            padding: 0,
          }}
        >
          ×
        </button>
      ) : null}
    </div>
  );
}

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
  const [leaderQuery, setLeaderQuery] = useState("");
  const [taskActionLoading, setTaskActionLoading] = useState<Record<string, boolean>>({});

  const [selectedFileName, setSelectedFileName] = useState("");
  const [showTaskEditor, setShowTaskEditor] = useState(false);

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

    const error = (payload as { error?: unknown }).error;
    if (typeof error === "string") {
      return error;
    }

    return "";
  }

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

    const normalizedLeaderQuery = leaderQuery.trim();
    const selectedLeaderOption = teamOptions.find((item) => item.leaderId === leaderId);
    if (normalizedLeaderQuery && !leaderId) {
      setError("团队绑定未生效：请从候选项中明确选择一个团队（不要只输入关键字）");
      return;
    }
    if (leaderId && !selectedLeaderOption) {
      setError("团队绑定异常：未找到对应团队，请重新选择后再提交");
      return;
    }

    setCreating(true);

    const sessionName = selectedLeaderOption?.sessionName?.trim() || undefined;

    const result = await caoRequest("POST", "/console/tasks/scheduled", {
      body: {
        file_name: selectedFileName.trim() || undefined,
        flow_name: selectedFileName.trim() ? undefined : flowName.trim() || undefined,
        flow_content: flowContent.trim(),
        session_name: sessionName,
        leader_id: leaderId.trim() || undefined,
      },
    });

    if (!result.ok) {
      const detail = extractErrorDetail(result.data);
      setError(detail ? `创建定时任务失败：${detail}` : "创建定时任务失败");
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
      `/console/tasks/scheduled/files/${encodeURI(fileName)}`
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
    const actionKey = `run:${name}`;
    setTaskActionLoading((previous) => ({ ...previous, [actionKey]: true }));
    const result = await caoRequest("POST", `/console/tasks/scheduled/${name}/run`);
    if (!result.ok) {
      setError("触发定时任务失败");
      setTaskActionLoading((previous) => ({ ...previous, [actionKey]: false }));
      return;
    }
    await loadTasks();
    setTaskActionLoading((previous) => ({ ...previous, [actionKey]: false }));
  }

  async function toggleScheduledTask(name: string, enabled: boolean) {
    const action = enabled ? "disable" : "enable";
    const actionKey = `toggle:${name}`;
    setTaskActionLoading((previous) => ({ ...previous, [actionKey]: true }));
    const result = await caoRequest("POST", `/console/tasks/scheduled/${name}/${action}`);
    if (!result.ok) {
      setError(enabled ? "暂停任务失败" : "启用任务失败");
      setTaskActionLoading((previous) => ({ ...previous, [actionKey]: false }));
      return;
    }
    await loadTasks();
    setTaskActionLoading((previous) => ({ ...previous, [actionKey]: false }));
  }

  async function deleteScheduledTask(name: string) {
    const actionKey = `delete:${name}`;
    setTaskActionLoading((previous) => ({ ...previous, [actionKey]: true }));
    const result = await caoRequest("DELETE", `/console/tasks/scheduled/${name}`);
    if (!result.ok) {
      setError("删除任务失败");
      setTaskActionLoading((previous) => ({ ...previous, [actionKey]: false }));
      return;
    }
    await loadTasks();
    setTaskActionLoading((previous) => ({ ...previous, [actionKey]: false }));
  }

  const teams = data?.teams || [];
  const teamOptions = teams.map((team) => {
    const leader = team.leader;
    const teamAlias = (team.team_alias || "").trim();
    const primary = teamAlias || leader.alias || leader.session_name || leader.id;
    return {
      leaderId: leader.id,
      sessionName: leader.session_name || "",
      label: `${primary} · ${leader.agent_profile || "unknown"} · ${leader.id}`,
    };
  });
  const selectedLeaderOption = teamOptions.find((item) => item.leaderId === leaderId);
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
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, marginBottom: showTaskEditor ? 8 : 0 }}>
            <SectionTitle title="新建/编辑定时任务" />
            <SecondaryButton
              type="button"
              onClick={() => setShowTaskEditor((previous) => !previous)}
              style={{ padding: "6px 10px" }}
              aria-expanded={showTaskEditor}
            >
              {showTaskEditor ? "收起" : "展开配置"}
            </SecondaryButton>
          </div>

          {showTaskEditor ? (
            <>
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
                <div>
                  <SearchableDatalistInput
                    value={leaderQuery}
                    onChange={(event) => {
                      const query = event.target.value;
                      const normalizedQuery = query.trim();
                      setLeaderQuery(query);
                      const matched = teamOptions.find(
                        (item) =>
                          item.label === normalizedQuery ||
                          item.leaderId === normalizedQuery ||
                          item.sessionName === normalizedQuery
                      );
                      setLeaderId(matched ? matched.leaderId : "");
                    }}
                    onClear={() => {
                      setLeaderQuery("");
                      setLeaderId("");
                    }}
                    list="task-team-options"
                    placeholder="搜索并选择绑定团队（可选）"
                  />
                  <datalist id="task-team-options">
                    {teamOptions.map((item) => (
                      <option key={`team-option-${item.leaderId}`} value={item.label} />
                    ))}
                  </datalist>
                </div>
                <TextInput
                  value={flowName}
                  onChange={(event) => setFlowName(event.target.value)}
                  placeholder="Flow 名称（新建时可选，编辑已有文件时将自动带出）"
                />
              </div>

              <div style={{ color: "var(--text-dim)", fontSize: 12, marginBottom: 10 }}>
                {loadingFileContent
                  ? "任务文件加载中..."
                  : "选择已有文件后会回填到编辑器；提交时将保存到原文件并发起任务。未选择文件时将按名称创建新文件。"}
              </div>
              <div style={{ color: "var(--text-dim)", fontSize: 12, marginBottom: 10 }}>
                {leaderId && selectedLeaderOption
                  ? `当前绑定团队：${selectedLeaderOption.label}`
                  : "当前绑定团队：不绑定"}
              </div>
              <form
                onSubmit={createScheduledTask}
                style={{
                  display: "grid",
                  gap: 10,
                  alignItems: "stretch",
                }}
              >
                <CodeEditorInput
                  value={flowContent}
                  onChange={setFlowContent}
                  language="auto"
                  fileName={selectedFileName || flowName}
                  showToolbar
                  enableFormat
                  required
                  placeholder="请输入完整 flow markdown（含 frontmatter）"
                  maxHeight={560}
                  style={{ width: "100%", minHeight: 320 }}
                />
                <PrimaryButton
                  type="submit"
                  disabled={creating}
                  style={{ minHeight: 38, width: "fit-content", justifySelf: "end", padding: "8px 16px" }}
                >
                  {creating
                    ? "提交中..."
                    : selectedFileName
                      ? "保存并发起任务"
                      : "创建并发起任务"}
                </PrimaryButton>
              </form>
            </>
          ) : (
            <div style={{ color: "var(--text-dim)", fontSize: 12 }}>点击展开配置后新建或编辑定时任务</div>
          )}
        </SectionCard>

        {teams.length === 0 ? (
          <EmptyState text="暂无团队任务数据" />
        ) : (
          teams.map((team) => (
            <SectionCard key={team.leader.id}>
              <div style={{ color: "var(--text-bright)", fontWeight: 700, marginBottom: 10 }}>
                团队：{team.team_alias || team.leader.session_name || team.leader.id}
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
                        {task.task_title ? (
                          <div
                            title={task.task_title}
                            style={{
                              color: "var(--text-bright)",
                              fontWeight: 700,
                              whiteSpace: "nowrap",
                              overflow: "hidden",
                              textOverflow: "ellipsis",
                            }}
                          >
                            当前任务：{task.task_title}
                          </div>
                        ) : null}
                        <div style={{ color: "var(--text-dim)", fontSize: 12, marginBottom: 4 }}>
                          {task.agent_profile || "unknown"} · {task.terminal_id}
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
                    team.scheduled_tasks.map((task) => {
                        const isRunning = Boolean(taskActionLoading[`run:${task.name}`]);
                        const isToggling = Boolean(taskActionLoading[`toggle:${task.name}`]);
                        const isDeleting = Boolean(taskActionLoading[`delete:${task.name}`]);
                        const isBusy = isRunning || isToggling || isDeleting;
                        return (
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
                                disabled={isBusy}
                                style={{ padding: "4px 8px", fontSize: 12 }}
                              >
                                {isRunning ? "触发中..." : "手动触发"}
                              </SecondaryButton>
                              <SecondaryButton
                                type="button"
                                onClick={() => toggleScheduledTask(task.name, task.enabled)}
                                disabled={isBusy}
                                style={{ padding: "4px 8px", fontSize: 12 }}
                              >
                                {isToggling ? "处理中..." : task.enabled ? "暂停" : "启用"}
                              </SecondaryButton>
                              <SecondaryButton
                                type="button"
                                onClick={() => deleteScheduledTask(task.name)}
                                disabled={isBusy}
                                style={{ padding: "4px 8px", fontSize: 12 }}
                              >
                                {isDeleting ? "删除中..." : "删除"}
                              </SecondaryButton>
                            </div>
                          </div>
                        );
                      })
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
              (() => {
                const isToggling = Boolean(taskActionLoading[`toggle:${task.name}`]);
                const isDeleting = Boolean(taskActionLoading[`delete:${task.name}`]);
                const isBusy = isToggling || isDeleting;

                return (
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
                    <div style={{ color: "var(--text-dim)", fontSize: 12, marginTop: 2, marginBottom: 8 }}>
                      {task.schedule} · {task.agent_profile}
                    </div>
                    <div style={{ display: "flex", marginBottom: 8 }}>
                      <StatusPill text={task.enabled ? "已启用" : "已暂停"} active={task.enabled} />
                    </div>
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      <SecondaryButton
                        type="button"
                        onClick={() => toggleScheduledTask(task.name, task.enabled)}
                        disabled={isBusy}
                        style={{ padding: "4px 8px", fontSize: 12 }}
                      >
                        {isToggling ? "处理中..." : task.enabled ? "暂停" : "启用"}
                      </SecondaryButton>
                      <SecondaryButton
                        type="button"
                        onClick={() => deleteScheduledTask(task.name)}
                        disabled={isBusy}
                        style={{ padding: "4px 8px", fontSize: 12 }}
                      >
                        {isDeleting ? "删除中..." : "删除"}
                      </SecondaryButton>
                    </div>
                  </div>
                );
              })()
            ))}
          </SectionCard>
        )}
      </PageShell>
    </RequireAuth>
  );
}

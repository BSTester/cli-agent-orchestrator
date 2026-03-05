"use client";

import { FormEvent, InputHTMLAttributes, useCallback, useEffect, useState } from "react";

import ConsoleNav from "@/components/ConsoleNav";
import {
  CodeEditorInput,
  DataTable,
  DataTd,
  DataTh,
  EmptyState,
  ErrorBanner,
  PageIntro,
  PageShell,
  PrimaryButton,
  SecondaryButton,
  SectionCard,
  SectionTitle,
  SelectInput,
  StatusPill,
  SuccessButton,
  TextInput,
} from "@/components/ConsoleTheme";
import RequireAuth from "@/components/RequireAuth";
import {
  AgentProfileFileResponse,
  caoRequest,
  ConsoleAgent,
  ConsoleAgentProfileFilesResponse,
  ConsoleAgentProfilesResponse,
  ConsoleHomeWorkdirsResponse,
  CreateAgentProfileRequest,
  CreateAgentProfileResponse,
  ConsoleOrganization,
  InstallAgentProfileResponse,
} from "@/lib/cao";
import { isStatusActive, toStatusLabel } from "@/lib/status";

const builtInProfiles = ["code_supervisor", "developer", "reviewer"];

const providers = [
  "",
  "kiro_cli",
  "claude_code",
  "codex",
  "qoder_cli",
  "codebuddy",
  "copilot",
];

const defaultProfileTemplate = `---
name: data_analyst
description: Analyze data and summarize key business insights.
provider: codex
mcpServers:
  cao-mcp-server:
    type: stdio
    command: uvx
    args:
      - "--from"
      - "git+https://github.com/BSTester/cli-agent-orchestrator.git@main"
      - "cao-mcp-server"
---

# DATA ANALYST

你是一名数据分析岗位 Agent，请按以下原则工作：

1. 先明确目标、口径与数据范围。
2. 输出关键指标、趋势和异常点。
3. 给出可执行建议，并标注假设与风险。
`;

const defaultProfileDisplayName =
  (function extractDefaultDisplayName() {
    const match = defaultProfileTemplate.match(/^---\s*\n([\s\S]*?)\n---/);
    if (!match) {
      return "";
    }
    const nameMatch = match[1].match(/^\s*name\s*:\s*(.+)\s*$/m);
    return nameMatch ? nameMatch[1].trim() : "";
  })() || "";

function extractProfileDisplayName(content: string): string {
  const match = content.match(/^---\s*\n([\s\S]*?)\n---/);
  if (!match) {
    return "";
  }
  const nameMatch = match[1].match(/^\s*name\s*:\s*(.+)\s*$/m);
  return nameMatch ? nameMatch[1].trim() : "";
}

function ensureProfileNameInContent(content: string, profileName: string): string {
  const normalizedProfileName = profileName.trim();
  if (!normalizedProfileName) {
    return content;
  }

  const frontmatterMatch = content.match(/^---\s*\n([\s\S]*?)\n---\s*/);
  if (!frontmatterMatch) {
    return ["---", `name: ${normalizedProfileName}`, "---", "", content].join("\n");
  }

  const frontmatter = frontmatterMatch[1];
  const hasNameField = /\bname\s*:/m.test(frontmatter);
  if (hasNameField) {
    return content;
  }

  const updatedFrontmatter = `name: ${normalizedProfileName}\n${frontmatter}`.trimEnd();

  return content.replace(frontmatterMatch[0], `---\n${updatedFrontmatter}\n---\n`);
}

function normalizeProfileFileName(input: string): string {
  const fallback = `profile_${Date.now()}`;
  const normalizedInput = (input || "").trim().replace(/\.md$/i, "");
  const base = normalizedInput || fallback;
  const sanitized = base.replace(/[^A-Za-z0-9_-]/g, "_");
  return sanitized || fallback;
}

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

export default function OrganizationPage() {
  const [data, setData] = useState<ConsoleOrganization | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [profileOptions, setProfileOptions] = useState<string[]>([]);

  const [mainProfile, setMainProfile] = useState("");
  const [mainProvider, setMainProvider] = useState("");
  const [mainTeamAlias, setMainTeamAlias] = useState("");
  const [homeSubdirs, setHomeSubdirs] = useState<string[]>([]);
  const [mainTeamWorkdirName, setMainTeamWorkdirName] = useState("");
  const [editingLeaderTarget, setEditingLeaderTarget] = useState<{
    leaderId: string;
    fallbackWorkingDirectory?: string;
  } | null>(null);
  const [creatingMain, setCreatingMain] = useState(false);

  const [workerProfile, setWorkerProfile] = useState("");
  const [workerProvider, setWorkerProvider] = useState("");
  const [workerLeaderId, setWorkerLeaderId] = useState("");
  const [workerLeaderQuery, setWorkerLeaderQuery] = useState("");
  const [workerAlias, setWorkerAlias] = useState("");
  const [creatingWorker, setCreatingWorker] = useState(false);

  const [newAgentName, setNewAgentName] = useState(defaultProfileDisplayName);
  const [profileFiles, setProfileFiles] = useState<ConsoleAgentProfileFilesResponse["files"]>([]);
  const [selectedProfileFileName, setSelectedProfileFileName] = useState("");
  const [newAgentPrompt, setNewAgentPrompt] = useState(defaultProfileTemplate);
  const [loadingProfileFile, setLoadingProfileFile] = useState(false);
  const [creatingProfile, setCreatingProfile] = useState(false);
  const [deletingProfile, setDeletingProfile] = useState(false);
  const [showProfileCard, setShowProfileCard] = useState(false);
  const [showTeamCard, setShowTeamCard] = useState(false);
  const [deleteProfileTarget, setDeleteProfileTarget] = useState<{ profileName: string } | null>(null);
  const [offboardTarget, setOffboardTarget] = useState<{ agentId: string; sessionName: string; terminalId: string } | null>(null);
  const [disbandTarget, setDisbandTarget] = useState<{
    leaderId: string;
    leaderName: string;
    sessionName: string;
    memberIds: string[];
  } | null>(null);

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

  const loadOrganization = useCallback(async () => {
    const result = await caoRequest<ConsoleOrganization>("GET", "/console/organization");
    if (!result.ok) {
      setError("获取组织结构失败");
      return;
    }
    setData(result.data);
    setError("");
  }, []);

  const loadProfileOptions = useCallback(async () => {
    const result = await caoRequest<ConsoleAgentProfilesResponse>(
      "GET",
      "/console/agent-profiles"
    );
    if (!result.ok) {
      setProfileOptions(builtInProfiles);
      setError("获取 Agent 类型列表失败，已回退内置类型");
      return;
    }
    const profiles = Array.from(
      new Set([...(result.data.profiles || []), ...builtInProfiles])
    ).sort();
    setProfileOptions(profiles);

    const preferredMainProfile = profiles.includes("code_supervisor")
      ? "code_supervisor"
      : profiles.includes("developer")
        ? "developer"
        : profiles[0] || "";

    const preferredWorkerProfile = profiles.includes("developer")
      ? "developer"
      : profiles[0] || "";

    setMainProfile((previous) => {
      if (!previous || !profiles.includes(previous)) {
        return preferredMainProfile;
      }
      return previous;
    });
    setWorkerProfile((previous) => {
      if (!previous || !profiles.includes(previous)) {
        return preferredWorkerProfile;
      }
      return previous;
    });
  }, []);

  const loadHomeWorkdirOptions = useCallback(async () => {
    const result = await caoRequest<ConsoleHomeWorkdirsResponse>("GET", "/console/workdirs/home");
    if (!result.ok) {
      setError("获取 workspace 工作目录选项失败");
      return;
    }

    const names = (result.data.directories || []).map((item) => item.name).filter(Boolean);
    setHomeSubdirs(names);
  }, []);

  const loadProfileFiles = useCallback(async () => {
    const result = await caoRequest<ConsoleAgentProfileFilesResponse>(
      "GET",
      "/console/agent-profiles/files"
    );
    if (!result.ok) {
      setError("获取岗位文件列表失败");
      return;
    }
    setProfileFiles(result.data.files || []);
  }, []);

  async function onSelectProfileFile(fileName: string) {
    setSelectedProfileFileName(fileName);
    if (!fileName) {
      setNewAgentName(defaultProfileDisplayName);
      setNewAgentPrompt(defaultProfileTemplate);
      return;
    }

    setLoadingProfileFile(true);
    const result = await caoRequest<AgentProfileFileResponse>(
      "GET",
      `/console/agent-profiles/files/${encodeURIComponent(fileName)}`
    );

    if (!result.ok) {
      setError("读取岗位文件失败");
      setLoadingProfileFile(false);
      return;
    }

    const profileContent = result.data.content || "";
    const displayName =
      result.data.display_name ||
      extractProfileDisplayName(profileContent) ||
      result.data.profile ||
      fileName.replace(/\.md$/i, "");

    setNewAgentName(displayName);
    setNewAgentPrompt(profileContent);
    setLoadingProfileFile(false);
  }

  function onProfileFileInputChange(fileName: string) {
    setSelectedProfileFileName(fileName);

    if (!fileName) {
      setNewAgentName(defaultProfileDisplayName);
      setNewAgentPrompt(defaultProfileTemplate);
      return;
    }

    const exists = profileFiles.some((fileItem) => fileItem.file_name === fileName);
    if (exists) {
      void onSelectProfileFile(fileName);
    }
  }

  async function shutdownSessionByTerminal(agentId: string, terminalId?: string, sessionName?: string) {
    if (!terminalId) {
      setError("退出团队失败：目标Agent没有终端信息");
      setNotice("");
      return;
    }

    setError("");
    setNotice("");
    const result = await caoRequest("DELETE", `/terminals/${terminalId}`);
    if (!result.ok) {
      const detail = extractErrorDetail(result.data);
      setError(detail ? `退出团队失败：${detail}` : "退出团队失败：无法关闭对应终端");
      setNotice("");
      return;
    }

    setNotice(`已退出团队：${agentId}${sessionName ? `（${sessionName}）` : ""}`);

    await loadOrganization();
  }

  function requestShutdown(agentId: string, terminalId?: string, sessionName?: string) {
    if (!terminalId) {
      setError("退出团队失败：目标Agent没有终端信息");
      return;
    }

    setOffboardTarget({ agentId, terminalId, sessionName: sessionName || "-" });
    setError("");
  }

  function cancelShutdown() {
    setOffboardTarget(null);
    setNotice("已取消退出团队操作");
    setError("");
  }

  async function confirmShutdown() {
    if (!offboardTarget) {
      return;
    }

    const currentTarget = offboardTarget;
    setOffboardTarget(null);
    await shutdownSessionByTerminal(currentTarget.agentId, currentTarget.terminalId, currentTarget.sessionName);
  }

  function requestDisbandTeam(leader: ConsoleAgent, members: ConsoleAgent[]) {
    const memberIds = members.map((member) => member.id).filter(Boolean);
    setDisbandTarget({
      leaderId: leader.id,
      leaderName: leader.alias || leader.id,
      sessionName: leader.session_name || "",
      memberIds,
    });
    setError("");
  }

  function cancelDisbandTeam() {
    setDisbandTarget(null);
    setNotice("已取消解散团队操作");
    setError("");
  }

  async function confirmDisbandTeam() {
    if (!disbandTarget) {
      return;
    }

    const currentTarget = disbandTarget;
    setDisbandTarget(null);
    setError("");
    setNotice("");

    const result = await caoRequest(
      "POST",
      `/console/organization/${encodeURIComponent(currentTarget.leaderId)}/disband`,
      {
        body: {
          session_name: currentTarget.sessionName || undefined,
        },
      }
    );
    if (!result.ok) {
      const detail = extractErrorDetail(result.data);
      setError(detail ? `解散团队失败：${detail}` : "解散团队失败");
      await loadOrganization();
      return;
    }

    setNotice(`已解散团队：${currentTarget.leaderName}${currentTarget.sessionName ? `（${currentTarget.sessionName}）` : ""}`);

    await loadOrganization();
  }

  async function onboardNewEmployee(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedAgentDisplayName = newAgentName.trim();
    if (!trimmedAgentDisplayName) {
      setError("岗位名称不能为空");
      return;
    }
    const trimmedPrompt = newAgentPrompt.trim();
    if (!trimmedPrompt) {
      setError("系统提示词不能为空");
      return;
    }
    setCreatingProfile(true);
    setError("");

    const selectedProfileFile = profileFiles.find(
      (fileItem) => fileItem.file_name === selectedProfileFileName.trim()
    );
    const isEditing = Boolean(selectedProfileFile);
    const resolvedProfileName = isEditing
      ? (selectedProfileFile?.file_name || "").replace(/\.md$/i, "")
      : normalizeProfileFileName(selectedProfileFileName || "");
    const contentWithName = ensureProfileNameInContent(trimmedPrompt, resolvedProfileName);
    setNewAgentPrompt(contentWithName);

    if (isEditing) {
      const targetProfile = (selectedProfileFile?.file_name || "").replace(/\.md$/i, "");
      const result = await caoRequest(
        "PUT",
        `/console/agent-profiles/${encodeURIComponent(targetProfile)}`,
        { body: { content: contentWithName, display_name: trimmedAgentDisplayName } }
      );
      if (!result.ok) {
        const detail = extractErrorDetail(result.data);
        setError(detail ? `更新岗位文件失败：${detail}` : "更新岗位文件失败");
        setCreatingProfile(false);
        return;
      }

      const reinstallResult = await caoRequest<InstallAgentProfileResponse>(
        "POST",
        `/console/agent-profiles/${encodeURIComponent(targetProfile)}/install`
      );
      if (!reinstallResult.ok || !reinstallResult.data.ok) {
        const detail = extractErrorDetail(reinstallResult.data);
        setError(detail ? `岗位文件已更新，但重装失败：${detail}` : "岗位文件已更新，但重装失败，请检查后端日志");
        setCreatingProfile(false);
        return;
      }

      setCreatingProfile(false);
      await loadProfileFiles();
      await loadProfileOptions();
      setNotice("岗位文件已更新并重装完成");
      return;
    }

    if (!/^[A-Za-z0-9_-]+$/.test(resolvedProfileName)) {
      setError("岗位文件名称无效");
      setCreatingProfile(false);
      return;
    }

    const body: CreateAgentProfileRequest = {
      name: resolvedProfileName,
      content: contentWithName,
      display_name: trimmedAgentDisplayName,
    };

    const result = await caoRequest<CreateAgentProfileResponse>(
      "POST",
      "/console/agent-profiles",
      { body }
    );

    if (!result.ok) {
      const detail = extractErrorDetail(result.data);
      setError(detail ? `创建岗位失败：${detail}` : "创建岗位失败，请检查名称是否重复或格式是否正确");
      setCreatingProfile(false);
      return;
    }

    const profileName = result.data.profile;
    const installResult = await caoRequest<InstallAgentProfileResponse>(
      "POST",
      `/console/agent-profiles/${profileName}/install`
    );
    if (!installResult.ok || !installResult.data.ok) {
      const detail = extractErrorDetail(installResult.data);
      setError(detail ? `岗位文件已保存，但安装失败：${detail}` : "岗位文件已保存，但安装失败，请检查后端日志");
      setCreatingProfile(false);
      return;
    }

    setNewAgentName(defaultProfileDisplayName);
    setNewAgentPrompt(defaultProfileTemplate);
    setSelectedProfileFileName("");
    setCreatingProfile(false);
    await loadProfileOptions();
    await loadProfileFiles();
    setNotice("新增岗位并安装完成");
  }

  async function deleteSelectedProfileFile() {
    const selectedProfileFile = profileFiles.find(
      (fileItem) => fileItem.file_name === selectedProfileFileName.trim()
    );
    if (!selectedProfileFile) {
      setError("请先选择一个已存在的岗位文件");
      return;
    }

    const profileName = (selectedProfileFile.file_name || "").replace(/\.md$/i, "");
    if (!profileName) {
      setError("岗位文件名称无效");
      return;
    }

    setDeleteProfileTarget({ profileName });
  }

  function cancelDeleteProfile() {
    setDeleteProfileTarget(null);
    setNotice("已取消删除岗位操作");
    setError("");
  }

  async function confirmDeleteProfile() {
    if (!deleteProfileTarget) {
      return;
    }

    const profileName = deleteProfileTarget.profileName;
    setDeleteProfileTarget(null);

    setDeletingProfile(true);
    setError("");

    const result = await caoRequest<InstallAgentProfileResponse>(
      "DELETE",
      `/console/agent-profiles/${encodeURIComponent(profileName)}`
    );

    if (!result.ok) {
      const detail = extractErrorDetail(result.data);
      setError(detail ? `删除岗位失败：${detail}` : "删除岗位失败");
      setDeletingProfile(false);
      return;
    }

    setDeletingProfile(false);
    setProfileFiles((previous) =>
      previous.filter((fileItem) => fileItem.profile !== profileName)
    );
    setProfileOptions((previous) => previous.filter((item) => item !== profileName));
    setMainProfile((previous) => (previous === profileName ? "" : previous));
    setWorkerProfile((previous) => (previous === profileName ? "" : previous));
    setMainProvider("");
    setWorkerProvider("");
    setMainTeamAlias("");
    setWorkerAlias("");
    setWorkerLeaderId("");
    setWorkerLeaderQuery("");
    setEditingLeaderTarget(null);
    setSelectedProfileFileName("");
    setNewAgentName(defaultProfileDisplayName);
    setNewAgentPrompt(defaultProfileTemplate);
    await loadProfileFiles();
    await loadProfileOptions();
    setNotice(`岗位 ${profileName} 已删除并执行卸载`);
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadOrganization();
    const bootstrapTimer = setTimeout(() => {
      void loadProfileOptions();
      void loadHomeWorkdirOptions();
      void loadProfileFiles();
    }, 0);
    const timer = setInterval(() => {
      void loadOrganization();
    }, 10000);
    return () => {
      clearInterval(timer);
      clearTimeout(bootstrapTimer);
    };
  }, [loadOrganization, loadProfileOptions, loadHomeWorkdirOptions, loadProfileFiles]);

  async function createMainAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreatingMain(true);
    setError("");

    if (editingLeaderTarget) {
      const body: {
        agent_profile: string;
        provider?: string;
        team_alias?: string;
        team_workdir_mode?: "existing" | "new";
        team_workdir_name?: string;
        working_directory?: string;
      } = {
        agent_profile: mainProfile.trim(),
      };

      if (mainProvider) {
        body.provider = mainProvider;
      }
      body.team_alias = mainTeamAlias;

      const workdirName = mainTeamWorkdirName.trim();
      if (workdirName) {
        body.team_workdir_name = workdirName;
        body.team_workdir_mode = homeSubdirs.includes(workdirName) ? "existing" : "new";
      } else if (editingLeaderTarget.fallbackWorkingDirectory) {
        body.working_directory = editingLeaderTarget.fallbackWorkingDirectory;
      }

      const result = await caoRequest(
        "PUT",
        `/console/organization/${encodeURIComponent(editingLeaderTarget.leaderId)}/leader`,
        { body }
      );
      if (!result.ok) {
        const detail = extractErrorDetail(result.data);
        setError(detail ? `编辑负责人失败：${detail}` : "编辑负责人失败");
        setCreatingMain(false);
        return;
      }

      setCreatingMain(false);
      setEditingLeaderTarget(null);
      setMainTeamAlias("");
      setMainTeamWorkdirName("");
      setNotice("负责人信息已更新并重启会话");
      await loadOrganization();
      await loadHomeWorkdirOptions();
      return;
    }

    const body: {
      role_type: "main";
      agent_profile: string;
      provider?: string;
      team_alias?: string;
      team_workdir_mode?: "existing" | "new";
      team_workdir_name?: string;
    } = {
      role_type: "main",
      agent_profile: mainProfile.trim(),
    };

    if (mainProvider) {
      body.provider = mainProvider;
    }
    if (mainTeamAlias.trim()) {
      body.team_alias = mainTeamAlias.trim();
    }

    const workdirName = mainTeamWorkdirName.trim();
    if (workdirName) {
      body.team_workdir_name = workdirName;
      body.team_workdir_mode = homeSubdirs.includes(workdirName) ? "existing" : "new";
    }

    const result = await caoRequest("POST", "/console/organization/create", { body });
    if (!result.ok) {
      const detail = extractErrorDetail(result.data);
      setError(detail ? `创建主控 Agent 失败：${detail}` : "创建主控 Agent 失败");
      setCreatingMain(false);
      return;
    }

    setCreatingMain(false);
    setMainTeamAlias("");
    setMainTeamWorkdirName("");
    await loadOrganization();
    await loadHomeWorkdirOptions();
  }

  function resolveTeamWorkdirInput(teamWorkingDirectory?: string): {
    workdirName: string;
    fallbackWorkingDirectory?: string;
  } {
    const normalized = String(teamWorkingDirectory || "").trim();
    if (!normalized) {
      return { workdirName: "" };
    }

    const match = normalized.match(/^\/home\/[^/]+\/workspace\/([^/]+)$/);
    if (match?.[1]) {
      return {
        workdirName: match[1],
        fallbackWorkingDirectory: normalized,
      };
    }

    return {
      workdirName: "",
      fallbackWorkingDirectory: normalized,
    };
  }

  function requestEditLeader(group: (typeof groups)[number]) {
    const leaderId = String(group.leader.id || "").trim();
    if (!leaderId) {
      setError("编辑负责人失败：未找到负责人ID");
      return;
    }

    const workdirInput = resolveTeamWorkdirInput(group.team_working_directory);
    setMainProfile(String(group.leader.agent_profile || "").trim());
    setMainProvider(String(group.leader.provider || "").trim());
    setMainTeamAlias(String(group.team_alias || "").trim());
    setMainTeamWorkdirName(workdirInput.workdirName);
    setEditingLeaderTarget({
      leaderId,
      fallbackWorkingDirectory: workdirInput.fallbackWorkingDirectory,
    });
    setShowTeamCard(true);
    setShowProfileCard(false);
    setNotice("");
    setError("");
  }

  function cancelEditLeader() {
    setEditingLeaderTarget(null);
    setMainTeamAlias("");
    setMainTeamWorkdirName("");
    setNotice("已取消编辑负责人");
    setError("");
  }

  async function createWorkerAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreatingWorker(true);
    setError("");

    const body: {
      role_type: "worker";
      agent_profile: string;
      provider?: string;
      leader_id?: string;
      agent_alias?: string;
    } = {
      role_type: "worker",
      agent_profile: workerProfile.trim(),
    };

    if (workerProvider) {
      body.provider = workerProvider;
    }
    if (workerLeaderId) {
      body.leader_id = workerLeaderId;
    }
    if (workerAlias.trim()) {
      body.agent_alias = workerAlias.trim();
    }

    const result = await caoRequest("POST", "/console/organization/create", { body });
    if (!result.ok) {
      const detail = extractErrorDetail(result.data);
      setError(detail ? `创建 Worker Agent 失败：${detail}` : "创建 Worker Agent 失败");
      setCreatingWorker(false);
      return;
    }

    setCreatingWorker(false);
    setWorkerAlias("");
    setWorkerLeaderId("");
    setWorkerLeaderQuery("");
    await loadOrganization();
  }

  const groups = data?.leader_groups ?? [];
  const leaders = data?.leaders ?? [];
  const groupAliases = new Map(
    groups
      .map((group) => [group.leader.id, (group.team_alias || "").trim()] as const)
      .filter(([, alias]) => Boolean(alias))
  );
  const mainProfileOptions = profileOptions;
  const workerProfileOptions = profileOptions;
  const workerLeaderOptions = leaders.map((leader: ConsoleAgent) => ({
    leaderId: leader.id,
    label: `${groupAliases.get(leader.id) || leader.id} · ${leader.agent_profile} · ${leader.id}`,
  }));
  const isEditingProfileFile = profileFiles.some(
    (fileItem) => fileItem.file_name === selectedProfileFileName.trim()
  );

  return (
    <RequireAuth>
      <ConsoleNav />
      <PageShell>
        <PageIntro
          title="组织管理"
          description="负责团队编制操作：新建团队、新增/编辑岗位、加入团队。"
        />

        {error && <ErrorBanner text={error} />}
        {notice && (
          <div
            style={{
              color: "var(--success)",
              border: "1px solid var(--success)",
              background: "var(--surface)",
              borderRadius: 10,
              padding: "8px 10px",
              marginBottom: 12,
              fontSize: 13,
            }}
            role="status"
          >
            {notice}
          </div>
        )}

        <section
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
            gap: 12,
            marginBottom: 14,
          }}
        >
          <SectionCard>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, marginBottom: showProfileCard ? 8 : 0 }}>
              <SectionTitle title="新增/编辑岗位" />
              <SecondaryButton
                type="button"
                onClick={() =>
                  setShowProfileCard((previous) => {
                    const next = !previous;
                    setShowTeamCard(next);
                    return next;
                  })
                }
                style={{ padding: "6px 10px" }}
                aria-expanded={showProfileCard}
              >
                {showProfileCard ? "收起" : "展开配置"}
              </SecondaryButton>
            </div>
            {showProfileCard ? (
              <form onSubmit={onboardNewEmployee}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
                <SearchableDatalistInput
                  value={selectedProfileFileName}
                  onChange={(e) => onProfileFileInputChange(e.target.value)}
                  onClear={() => onProfileFileInputChange("")}
                  list="agent-profile-file-options"
                  placeholder="选择/搜索已有岗位文件，或输入新文件名（文件名不依赖岗位名称）"
                />
                <TextInput
                  value={newAgentName}
                  onChange={(e) => setNewAgentName(e.target.value)}
                  required
                  placeholder="岗位名称（展示用，可输入中文）"
                />
              </div>
              <datalist id="agent-profile-file-options">
                {profileFiles.map((fileItem) => (
                  <option key={fileItem.file_name} value={fileItem.file_name}>
                    编辑：{fileItem.file_name}
                    {fileItem.display_name ? `（${fileItem.display_name}）` : ""}
                  </option>
                ))}
              </datalist>
              <CodeEditorInput
                value={newAgentPrompt}
                onChange={setNewAgentPrompt}
                language="markdown"
                showToolbar
                enableFormat
                required
                placeholder="岗位配置 markdown 内容"
                maxHeight={520}
                style={{ width: "100%", minHeight: 240, marginBottom: 10 }}
              />
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <div>
                  {isEditingProfileFile ? (
                    <SecondaryButton
                      type="button"
                      onClick={deleteSelectedProfileFile}
                      disabled={creatingProfile || loadingProfileFile || deletingProfile}
                      style={{ color: "var(--danger)", borderColor: "var(--danger)" }}
                    >
                      {deletingProfile ? "删除中..." : "删除岗位"}
                    </SecondaryButton>
                  ) : null}
                </div>
                <PrimaryButton
                  type="submit"
                  disabled={creatingProfile || loadingProfileFile || deletingProfile}
                >
                  {creatingProfile
                    ? "保存中..."
                    : isEditingProfileFile
                      ? "保存岗位文件"
                      : "保存岗位并完成安装"}
                </PrimaryButton>
              </div>
              </form>
            ) : (
              <div style={{ color: "var(--text-dim)", fontSize: 12 }}>点击展开配置后新建或编辑岗位</div>
            )}
          </SectionCard>

          <SectionCard>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, marginBottom: showTeamCard ? 8 : 0 }}>
              <SectionTitle title="团队编制管理" />
              <SecondaryButton
                type="button"
                onClick={() =>
                  setShowTeamCard((previous) => {
                    const next = !previous;
                    setShowProfileCard(next);
                    return next;
                  })
                }
                style={{ padding: "6px 10px" }}
                aria-expanded={showTeamCard}
              >
                {showTeamCard ? "收起" : "展开配置"}
              </SecondaryButton>
            </div>
            {showTeamCard ? (
              <>
                <div style={{ color: "var(--text-bright)", fontWeight: 700, marginBottom: 8 }}>
                  {editingLeaderTarget ? "编辑负责人" : "新增负责人"}
                </div>
                <form onSubmit={createMainAgent} style={{ display: "grid", gap: 10 }}>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                  <SearchableDatalistInput
                    value={mainProfile}
                    onChange={(e) => setMainProfile(e.target.value)}
                    onClear={() => setMainProfile("")}
                    list="main-profile-options"
                    placeholder="选择/搜索负责人岗位"
                    required
                  />
                  <SelectInput
                    value={mainProvider}
                    onChange={(e) => setMainProvider(e.target.value)}
                  >
                    {providers.map((item) => (
                      <option key={item || "default-main"} value={item}>
                        {item || "自动选择 provider"}
                      </option>
                    ))}
                  </SelectInput>
                  <TextInput
                    value={mainTeamAlias}
                    onChange={(e) => setMainTeamAlias(e.target.value)}
                    placeholder="团队别名（可选）"
                  />
                  <SearchableDatalistInput
                    value={mainTeamWorkdirName}
                    onChange={(e) => setMainTeamWorkdirName(e.target.value)}
                    onClear={() => setMainTeamWorkdirName("")}
                    placeholder="团队工作目录（输入或选择 workspace 一级目录）"
                    list="main-team-workdir-options"
                  />
                  </div>

                  <datalist id="main-profile-options">
                    {mainProfileOptions.map((profileName) => (
                      <option key={`main-${profileName}`} value={profileName} />
                    ))}
                  </datalist>

                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: 10, alignItems: "center" }}>
                    <div style={{ color: "var(--text-dim)", fontSize: 12 }}>
                      根目录：~/workspace（输入新目录名会自动在 workspace 下创建一级目录）
                    </div>
                    <div style={{ color: "var(--text-dim)", fontSize: 12 }}>
                      可输入新目录名，也可下拉选择已有一级目录
                    </div>
                    <div style={{ display: "flex", justifySelf: "end", gap: 8 }}>
                      {editingLeaderTarget ? (
                        <SecondaryButton
                          type="button"
                          onClick={cancelEditLeader}
                          disabled={creatingMain}
                          style={{ width: "fit-content" }}
                        >
                          取消编辑
                        </SecondaryButton>
                      ) : null}
                      <PrimaryButton
                        type="submit"
                        disabled={creatingMain}
                        style={{ width: "fit-content" }}
                      >
                        {creatingMain ? "处理中..." : editingLeaderTarget ? "编辑团队" : "启动团队"}
                      </PrimaryButton>
                    </div>
                  </div>

                  <datalist id="main-team-workdir-options">
                    {homeSubdirs.map((dirName) => (
                      <option key={`main-team-workdir-${dirName}`} value={dirName} />
                    ))}
                  </datalist>
                </form>

                <div style={{ height: 1, background: "var(--border)", margin: "14px 0" }} />

                <div style={{ color: "var(--text-bright)", fontWeight: 700, marginBottom: 8 }}>新增员工</div>
                <form onSubmit={createWorkerAgent} style={{ display: "grid", gap: 10 }}>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                    <SearchableDatalistInput
                      value={workerProfile}
                      onChange={(e) => setWorkerProfile(e.target.value)}
                      onClear={() => setWorkerProfile("")}
                      list="worker-profile-options"
                      placeholder="选择/搜索员工岗位"
                      required
                    />
                    <SelectInput
                      value={workerProvider}
                      onChange={(e) => setWorkerProvider(e.target.value)}
                    >
                      {providers.map((item) => (
                        <option key={item || "default-worker"} value={item}>
                          {item || "自动选择 provider"}
                        </option>
                      ))}
                    </SelectInput>
                  </div>
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: 10, alignItems: "center" }}>
                    <SearchableDatalistInput
                      value={workerLeaderQuery}
                      onChange={(e) => {
                        const nextValue = e.target.value;
                        setWorkerLeaderQuery(nextValue);
                        const matched = workerLeaderOptions.find((item) => item.label === nextValue);
                        setWorkerLeaderId(matched ? matched.leaderId : "");
                      }}
                      onClear={() => {
                        setWorkerLeaderQuery("");
                        setWorkerLeaderId("");
                      }}
                      list="worker-leader-options"
                      placeholder="选择/搜索团队（可留空）"
                    />
                    <datalist id="worker-profile-options">
                      {workerProfileOptions.map((profileName) => (
                        <option key={`worker-${profileName}`} value={profileName} />
                      ))}
                    </datalist>
                    <datalist id="worker-leader-options">
                      {workerLeaderOptions.map((option) => (
                        <option key={option.leaderId} value={option.label} />
                      ))}
                    </datalist>
                    <TextInput
                      value={workerAlias}
                      onChange={(e) => setWorkerAlias(e.target.value)}
                      placeholder="员工别名（可选）"
                    />
                    <SuccessButton
                      type="submit"
                      disabled={creatingWorker}
                      style={{ width: "fit-content", justifySelf: "end" }}
                    >
                      {creatingWorker ? "加入中..." : "加入团队"}
                    </SuccessButton>
                  </div>
                </form>
              </>
            ) : (
              <div style={{ color: "var(--text-dim)", fontSize: 12 }}>点击展开配置后创建或加入团队</div>
            )}
          </SectionCard>
        </section>

        <SectionCard>
          <SectionTitle title="集团团队架构" />
          {groups.length === 0 ? (
            <EmptyState text="暂无团队" />
          ) : (
            groups.map((group) => (
              <div key={group.leader.id} style={{ border: "1px solid var(--border)", borderRadius: 8, padding: 10, marginBottom: 10 }}>
                <div style={{ marginBottom: 8, display: "flex", justifyContent: "space-between", gap: 8, alignItems: "center" }}>
                  <div>
                    <span style={{ color: "var(--text-bright)", fontWeight: 700 }}>
                      {group.team_alias || group.leader.id}
                    </span>
                    <span style={{ color: "var(--text-dim)", marginLeft: 8 }}>
                      负责人：{group.leader.alias || group.leader.id} · {group.leader.agent_profile} · {group.leader.provider || "-"} · {toStatusLabel(group.leader.status)}
                    </span>
                    {group.team_working_directory ? (
                      <span style={{ color: "var(--text-dim)", marginLeft: 8 }}>
                        工作目录：{group.team_working_directory}
                      </span>
                    ) : null}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <SecondaryButton
                      type="button"
                      onClick={() => requestEditLeader(group)}
                      style={{ padding: "4px 8px", fontSize: 12 }}
                    >
                      编辑
                    </SecondaryButton>
                    <SecondaryButton
                      type="button"
                      onClick={() => requestDisbandTeam(group.leader, group.members)}
                      style={{ padding: "4px 8px", fontSize: 12 }}
                    >
                      解散团队
                    </SecondaryButton>
                  </div>
                </div>
                {group.members.length === 0 ? (
                  <EmptyState text="暂无直属 Worker" />
                ) : (
                  <div style={{ overflowX: "auto" }}>
                    <DataTable>
                      <thead>
                        <tr>
                          <DataTh>Worker ID</DataTh>
                          <DataTh>别名</DataTh>
                          <DataTh>Profile</DataTh>
                          <DataTh>Provider</DataTh>
                          <DataTh>状态</DataTh>
                          <DataTh>操作</DataTh>
                        </tr>
                      </thead>
                      <tbody>
                        {group.members.map((member) => (
                          <tr key={member.id} style={{ borderTop: "1px solid var(--border)" }}>
                            <DataTd mono>{member.id}</DataTd>
                            <DataTd>{member.alias || "-"}</DataTd>
                            <DataTd>{member.agent_profile}</DataTd>
                            <DataTd>{member.provider}</DataTd>
                            <DataTd>
                              <StatusPill
                                text={toStatusLabel(member.status)}
                                active={isStatusActive(member.status)}
                              />
                            </DataTd>
                            <DataTd>
                              <SecondaryButton
                                type="button"
                                onClick={() => requestShutdown(member.id, member.id, member.session_name)}
                                disabled={!member.id}
                                style={{ padding: "4px 8px", fontSize: 12 }}
                              >
                                退出团队
                              </SecondaryButton>
                            </DataTd>
                          </tr>
                        ))}
                      </tbody>
                    </DataTable>
                  </div>
                )}
              </div>
            ))
          )}
        </SectionCard>

        {offboardTarget && (
          <div
            style={{
              position: "fixed",
              inset: 0,
              zIndex: 50,
              background: "rgba(0,0,0,0.45)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: 16,
            }}
            onClick={cancelShutdown}
          >
            <div
              role="dialog"
              aria-modal="true"
              aria-label="离职确认"
              onClick={(event) => event.stopPropagation()}
              style={{
                width: "min(520px, 100%)",
                background: "var(--surface)",
                border: "1px solid var(--border)",
                borderRadius: 12,
                padding: 14,
              }}
            >
              <div style={{ color: "var(--text-bright)", fontWeight: 700, marginBottom: 8 }}>
                确认退出团队
              </div>
              <div style={{ color: "var(--text-dim)", fontSize: 13, marginBottom: 4 }}>
                Agent：{offboardTarget.agentId}
              </div>
              <div style={{ color: "var(--text-dim)", fontSize: 13, marginBottom: 12 }}>
                会话：{offboardTarget.sessionName}
              </div>
              <div style={{ color: "var(--text-dim)", fontSize: 12, marginBottom: 14 }}>
                确认后将关闭该成员终端并从当前组织架构中移除，不会影响负责人。
              </div>
              <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
                <SecondaryButton type="button" onClick={cancelShutdown}>
                  取消
                </SecondaryButton>
                <PrimaryButton type="button" onClick={() => void confirmShutdown()}>
                  确认退出
                </PrimaryButton>
              </div>
            </div>
          </div>
        )}

        {disbandTarget && (
          <div
            style={{
              position: "fixed",
              inset: 0,
              zIndex: 51,
              background: "rgba(0,0,0,0.45)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: 16,
            }}
            onClick={cancelDisbandTeam}
          >
            <div
              role="dialog"
              aria-modal="true"
              aria-label="解散团队确认"
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
                确认解散团队
              </div>
              <div style={{ color: "var(--text-dim)", fontSize: 13, marginBottom: 4 }}>
                负责人：{disbandTarget.leaderName}
              </div>
              <div style={{ color: "var(--text-dim)", fontSize: 13, marginBottom: 4 }}>
                会话：{disbandTarget.sessionName || "-"}
              </div>
              <div style={{ color: "var(--text-dim)", fontSize: 13, marginBottom: 12 }}>
                团队成员数：{disbandTarget.memberIds.length}
              </div>
              <div style={{ color: "var(--text-dim)", fontSize: 12, marginBottom: 14 }}>
                确认后将按会话一次性关闭当前团队全部终端，不会影响其他团队。
              </div>
              <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
                <SecondaryButton type="button" onClick={cancelDisbandTeam}>
                  取消
                </SecondaryButton>
                <PrimaryButton type="button" onClick={() => void confirmDisbandTeam()}>
                  确认解散
                </PrimaryButton>
              </div>
            </div>
          </div>
        )}

        {deleteProfileTarget && (
          <div
            style={{
              position: "fixed",
              inset: 0,
              zIndex: 52,
              background: "rgba(0,0,0,0.45)",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              padding: 16,
            }}
            onClick={cancelDeleteProfile}
          >
            <div
              role="dialog"
              aria-modal="true"
              aria-label="删除岗位确认"
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
                确认删除岗位
              </div>
              <div style={{ color: "var(--text-dim)", fontSize: 13, marginBottom: 12 }}>
                岗位：{deleteProfileTarget.profileName}
              </div>
              <div style={{ color: "var(--text-dim)", fontSize: 12, marginBottom: 14 }}>
                确认后将执行卸载并删除本地岗位配置文件，同时清理各 agent 终端的岗位配置。
              </div>
              <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
                <SecondaryButton type="button" onClick={cancelDeleteProfile}>
                  取消
                </SecondaryButton>
                <PrimaryButton type="button" onClick={() => void confirmDeleteProfile()}>
                  确认删除
                </PrimaryButton>
              </div>
            </div>
          </div>
        )}
      </PageShell>
    </RequireAuth>
  );
}

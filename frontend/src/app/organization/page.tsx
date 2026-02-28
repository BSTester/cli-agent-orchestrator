"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import ConsoleNav from "@/components/ConsoleNav";
import {
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
  TextAreaInput,
  TextInput,
} from "@/components/ConsoleTheme";
import RequireAuth from "@/components/RequireAuth";
import {
  caoRequest,
  ConsoleAgent,
  ConsoleAgentProfilesResponse,
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
  "q_cli",
  "qoder_cli",
  "opencode",
  "codebuddy",
  "copilot",
];

export default function OrganizationPage() {
  const [data, setData] = useState<ConsoleOrganization | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [profileOptions, setProfileOptions] = useState<string[]>([]);

  const [mainProfile, setMainProfile] = useState("");
  const [mainProvider, setMainProvider] = useState("");
  const [mainTeamAlias, setMainTeamAlias] = useState("");
  const [creatingMain, setCreatingMain] = useState(false);

  const [workerProfile, setWorkerProfile] = useState("");
  const [workerProvider, setWorkerProvider] = useState("");
  const [workerLeaderId, setWorkerLeaderId] = useState("");
  const [workerAlias, setWorkerAlias] = useState("");
  const [creatingWorker, setCreatingWorker] = useState(false);

  const [newAgentName, setNewAgentName] = useState("");
  const [newAgentDescription, setNewAgentDescription] = useState("");
  const [newAgentProvider, setNewAgentProvider] = useState("");
  const [newAgentPrompt, setNewAgentPrompt] = useState("");
  const [creatingProfile, setCreatingProfile] = useState(false);

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

    const workerProfiles = profiles.filter((profileName) => profileName !== "code_supervisor");

    if (!mainProfile || mainProfile !== "code_supervisor") {
      setMainProfile("code_supervisor");
    }
    if (!workerProfile || workerProfile === "code_supervisor") {
      const preferredWorker = workerProfiles.includes("developer")
        ? "developer"
        : workerProfiles[0] || "";
      setWorkerProfile(preferredWorker);
    }
  }, [mainProfile, workerProfile]);

  async function shutdownSessionByTerminal(agentId: string, sessionName?: string) {
    if (!sessionName) {
      setError("离职失败：目标Agent没有会话信息");
      setNotice("");
      return;
    }

    setError("");
    setNotice("");
    const result = await caoRequest("DELETE", `/sessions/${sessionName}`);
    if (!result.ok) {
      setError("离职失败：无法关闭对应会话");
      setNotice("");
      return;
    }

    setNotice(`已完成离职：${agentId}`);

    await loadOrganization();
  }

  async function confirmAndShutdown(agentId: string, sessionName?: string) {
    if (!sessionName) {
      setError("离职失败：目标Agent没有会话信息");
      return;
    }

    const confirmed = window.confirm(
      `确认办理离职吗？\n\nAgent：${agentId}\n会话：${sessionName}\n\n确认后将关闭该会话。`
    );

    if (!confirmed) {
      setNotice("已取消离职操作");
      setError("");
      return;
    }

    await shutdownSessionByTerminal(agentId, sessionName);
  }

  async function onboardNewEmployee(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreatingProfile(true);
    setError("");

    const body: CreateAgentProfileRequest = {
      name: newAgentName.trim(),
      description: newAgentDescription.trim(),
      system_prompt: newAgentPrompt.trim(),
    };
    if (newAgentProvider) {
      body.provider = newAgentProvider;
    }

    const result = await caoRequest<CreateAgentProfileResponse>(
      "POST",
      "/console/agent-profiles",
      { body }
    );

    if (!result.ok) {
      setError("创建自定义 Agent 类型失败，请检查名称是否重复或格式是否正确");
      setCreatingProfile(false);
      return;
    }

    const profileName = result.data.profile;
    const installResult = await caoRequest<InstallAgentProfileResponse>(
      "POST",
      `/console/agent-profiles/${profileName}/install`
    );
    if (!installResult.ok || !installResult.data.ok) {
      setError("岗位档案已保存，但安装失败，请检查后端日志");
      setCreatingProfile(false);
      return;
    }

    setNewAgentName("");
    setNewAgentDescription("");
    setNewAgentProvider("");
    setNewAgentPrompt("");
    setCreatingProfile(false);
    await loadProfileOptions();
  }

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadOrganization();
    const bootstrapTimer = setTimeout(() => {
      void loadProfileOptions();
    }, 0);
    const timer = setInterval(() => {
      void loadOrganization();
    }, 10000);
    return () => {
      clearInterval(timer);
      clearTimeout(bootstrapTimer);
    };
  }, [loadOrganization, loadProfileOptions]);

  async function createMainAgent(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreatingMain(true);
    setError("");

    const body: {
      role_type: "main";
      agent_profile: string;
      provider?: string;
      team_alias?: string;
    } = {
      role_type: "main",
      agent_profile: "code_supervisor",
    };

    if (mainProvider) {
      body.provider = mainProvider;
    }
    if (mainTeamAlias.trim()) {
      body.team_alias = mainTeamAlias.trim();
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
    await loadOrganization();
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
    await loadOrganization();
  }

  const groups = data?.leader_groups ?? [];
  const leaders = data?.leaders ?? [];
  const mainProfileOptions = ["code_supervisor"];
  const workerProfileOptions = profileOptions.filter((profileName) => profileName !== "code_supervisor");

  return (
    <RequireAuth>
      <ConsoleNav />
      <PageShell>
        <PageIntro
          title="组织管理"
          description="负责团队编制操作：新建团队、新入职员工、加入团队。"
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
            <SectionTitle title="新增岗位类型" />
            <form onSubmit={onboardNewEmployee}>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 10 }}>
              <TextInput
                value={newAgentName}
                onChange={(e) => setNewAgentName(e.target.value)}
                required
                placeholder="name，例如 data_analyst"
              />
              <TextInput
                value={newAgentDescription}
                onChange={(e) => setNewAgentDescription(e.target.value)}
                required
                placeholder="description"
              />
            </div>
            <div style={{ marginBottom: 10 }}>
              <SelectInput
                value={newAgentProvider}
                onChange={(e) => setNewAgentProvider(e.target.value)}
                style={{ width: "100%" }}
              >
                {providers.map((item) => (
                  <option key={item || "default-new-profile"} value={item}>
                    {item || "不指定 provider（按系统默认）"}
                  </option>
                ))}
              </SelectInput>
            </div>
            <TextAreaInput
              value={newAgentPrompt}
              onChange={(e) => setNewAgentPrompt(e.target.value)}
              required
              placeholder="系统提示词（markdown 内容）"
              style={{ width: "100%", minHeight: 120, marginBottom: 10 }}
            />
            <PrimaryButton
              type="submit"
              disabled={creatingProfile}
            >
              {creatingProfile ? "办理入职中..." : "保存岗位并完成安装"}
            </PrimaryButton>
            </form>
          </SectionCard>

          <SectionCard>
            <SectionTitle title="组建新团队（启动团队负责人）" />
            <form onSubmit={createMainAgent} style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr auto", gap: 10 }}>
            <SelectInput
              value={mainProfile}
              onChange={(e) => setMainProfile(e.target.value)}
              required
            >
              {mainProfileOptions.map((profileName) => (
                <option key={`main-${profileName}`} value={profileName}>
                  {profileName}
                </option>
              ))}
            </SelectInput>
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
            <PrimaryButton
              type="submit"
              disabled={creatingMain}
            >
              {creatingMain ? "组建中..." : "启动团队"}
            </PrimaryButton>
            </form>
          </SectionCard>
        </section>

        <SectionCard>
          <SectionTitle title="团队增员（入职执行员工）" />
          <form onSubmit={createWorkerAgent} style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr auto", gap: 10 }}>
            <SelectInput
              value={workerProfile}
              onChange={(e) => setWorkerProfile(e.target.value)}
              required
            >
              <option value="">请选择 Agent 类型</option>
              {workerProfileOptions.map((profileName) => (
                <option key={`worker-${profileName}`} value={profileName}>
                  {profileName}
                </option>
              ))}
            </SelectInput>
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
            <SelectInput
              value={workerLeaderId}
              onChange={(e) => setWorkerLeaderId(e.target.value)}
            >
              <option value="">不分配团队（独立团队编制）</option>
              {leaders.map((leader: ConsoleAgent) => (
                <option key={leader.id} value={leader.id}>
                  {leader.id} · {leader.agent_profile}
                </option>
              ))}
            </SelectInput>
            <TextInput
              value={workerAlias}
              onChange={(e) => setWorkerAlias(e.target.value)}
              placeholder="员工别名（可选）"
            />
            <SuccessButton
              type="submit"
              disabled={creatingWorker}
            >
              {creatingWorker ? "办理中..." : "办理入职"}
            </SuccessButton>
          </form>
        </SectionCard>

        <SectionCard>
          <SectionTitle title="集团团队架构（负责人 → 员工）" />
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
                      负责人：{group.leader.alias || group.leader.id} · {group.leader.agent_profile} · {toStatusLabel(group.leader.status)}
                    </span>
                  </div>
                  <SecondaryButton
                    type="button"
                    onClick={() => void confirmAndShutdown(group.leader.id, group.leader.session_name)}
                    disabled={!group.leader.session_name}
                    style={{ padding: "4px 8px", fontSize: 12 }}
                  >
                    办理离职
                  </SecondaryButton>
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
                                onClick={() => void confirmAndShutdown(member.id, member.session_name)}
                                disabled={!member.session_name}
                                style={{ padding: "4px 8px", fontSize: 12 }}
                              >
                                办理离职
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
      </PageShell>
    </RequireAuth>
  );
}

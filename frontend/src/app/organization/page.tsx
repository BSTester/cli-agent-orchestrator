"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

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

    if (!currentTarget.sessionName) {
      setError("解散团队失败：负责人缺少会话信息，无法按会话关闭");
      await loadOrganization();
      return;
    }

    const result = await caoRequest("DELETE", `/sessions/${encodeURIComponent(currentTarget.sessionName)}`);
    if (!result.ok) {
      const detail = extractErrorDetail(result.data);
      setError(detail ? `解散团队失败：${detail}` : "解散团队失败：无法关闭团队会话");
      await loadOrganization();
      return;
    }

    setNotice(`已解散团队：${currentTarget.leaderName}（${currentTarget.sessionName}）`);

    await loadOrganization();
  }

  async function onboardNewEmployee(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!newAgentPrompt.trim()) {
      setError("系统提示词不能为空");
      return;
    }
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
  const groupAliases = new Map(
    groups
      .map((group) => [group.leader.id, (group.team_alias || "").trim()] as const)
      .filter(([, alias]) => Boolean(alias))
  );
  const mainProfileOptions = ["code_supervisor"];
  const workerProfileOptions = profileOptions.filter((profileName) => profileName !== "code_supervisor");

  return (
    <RequireAuth>
      <ConsoleNav />
      <PageShell>
        <PageIntro
          title="组织管理"
          description="负责团队编制操作：新建团队、保存岗位类型、加入团队。"
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
            <CodeEditorInput
              value={newAgentPrompt}
              onChange={setNewAgentPrompt}
              language="markdown"
              showToolbar
              enableFormat
              required
              placeholder="系统提示词（markdown 内容）"
              style={{ width: "100%", minHeight: 240, marginBottom: 10 }}
            />
            <div style={{ display: "flex", justifyContent: "flex-end" }}>
              <PrimaryButton
                type="submit"
                disabled={creatingProfile}
              >
                {creatingProfile ? "保存中..." : "保存岗位并完成安装"}
              </PrimaryButton>
            </div>
            </form>
          </SectionCard>

          <SectionCard>
            <SectionTitle title="团队编制管理" />
            <div style={{ color: "var(--text-bright)", fontWeight: 700, marginBottom: 8 }}>新增负责人</div>
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

            <div style={{ height: 1, background: "var(--border)", margin: "14px 0" }} />

            <div style={{ color: "var(--text-bright)", fontWeight: 700, marginBottom: 8 }}>新增员工</div>
            <form onSubmit={createWorkerAgent} style={{ display: "grid", gap: 10 }}>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
                <SelectInput
                  value={workerProfile}
                  onChange={(e) => setWorkerProfile(e.target.value)}
                  required
                >
                  <option value="">岗位类型</option>
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
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr auto", gap: 10, alignItems: "center" }}>
                <SelectInput
                  value={workerLeaderId}
                  onChange={(e) => setWorkerLeaderId(e.target.value)}
                >
                  <option value="">不分配团队（独立团队编制）</option>
                  {leaders.map((leader: ConsoleAgent) => (
                    <option key={leader.id} value={leader.id}>
                      {(groupAliases.get(leader.id) || leader.id)} · {leader.agent_profile}
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
                  style={{ width: "fit-content", justifySelf: "end" }}
                >
                  {creatingWorker ? "加入中..." : "加入团队"}
                </SuccessButton>
              </div>
            </form>
          </SectionCard>
        </section>

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
                    onClick={() => requestDisbandTeam(group.leader, group.members)}
                    style={{ padding: "4px 8px", fontSize: 12 }}
                  >
                    解散团队
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
                确认后将按会话一次性关闭当前团队全部终端（等价于 shutdown --session），不会影响其他团队。
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
      </PageShell>
    </RequireAuth>
  );
}

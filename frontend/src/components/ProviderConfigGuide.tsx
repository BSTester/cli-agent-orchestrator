"use client";

import { useCallback, useEffect, useState, type ChangeEvent } from "react";

import TerminalDrawer from "@/components/TerminalDrawer";
import {
  CodeEditorInput,
  EmptyState,
  ErrorBanner,
  InfoHint,
  PageIntro,
  PageShell,
  PrimaryButton,
  SecondaryButton,
  SectionCard,
  SectionTitle,
  StatusPill,
  TextInput,
} from "@/components/ConsoleTheme";
import {
  caoRequest,
  getCaoErrorHint,
  type OpenClawFeishuConfigPayload,
  type ProviderConfigApplyPayload,
  type ProviderConfigApplyResponse,
  type ProviderGuideProvider,
  type ProviderGuideSummary,
} from "@/lib/cao";

type GuideVariant = "page" | "modal";

type ProviderFormState = {
  selected: boolean;
  mode: "account" | "api";
  apiBaseUrl: string;
  apiKey: string;
  defaultModel: string;
  compatibility: "openai" | "anthropic";
  feishuEnabled: boolean;
  feishuDomain: "feishu" | "lark";
  feishuConnectionMode: "websocket" | "webhook";
  feishuAppId: string;
  feishuAppSecret: string;
  feishuBotName: string;
  feishuVerificationToken: string;
  feishuDmPolicy: "pairing" | "allowlist" | "open" | "disabled";
  feishuAccountId: string;
};

type ProviderConfigGuideProps = {
  variant?: GuideVariant;
  onRequestClose?: () => void;
  defaultOpen?: boolean;
  autoOpen?: boolean;
};

type ActiveTerminalState = {
  terminalId: string;
  title: string;
  subtitle: string;
  providerId: string;
  action: "login" | "logout" | "configure";
};

/** Kiro login flow phase */
type KiroPhase = "idle" | "waiting_callback" | "callback_submitted";

const DEFAULT_ACCOUNT_MODE_PROVIDER_IDS = new Set([
  "claude_code",
  "codex",
  "copilot",
  "qoder_cli",
  "kiro_cli",
  "codebuddy",
]);

function createDefaultForm(provider: ProviderGuideProvider): ProviderFormState {
  const savedMode = provider.saved_settings.mode;
  const supportsApi = provider.supports_api_config;
  const mode = savedMode === "api" && supportsApi ? "api" : "account";
  const apiBaseUrl = String(provider.saved_settings.api_base_url || "").trim();
  const apiKey = String(provider.saved_settings.api_key || "").trim();
  const defaultModel = String(provider.saved_settings.default_model || "").trim();
  const compatibility =
    provider.saved_settings.compatibility === "anthropic" ? "anthropic" : "openai";
  const feishuRaw = provider.saved_settings.feishu;
  const feishu = feishuRaw && typeof feishuRaw === "object" ? feishuRaw : null;

  return {
    selected: provider.default_selected,
    mode: supportsApi ? mode : "account",
    apiBaseUrl,
    apiKey,
    defaultModel,
    compatibility,
    feishuEnabled: Boolean(feishu && (feishu as Record<string, unknown>).enabled),
    feishuDomain:
      (feishu && (feishu as Record<string, unknown>).domain === "lark") ? "lark" : "feishu",
    feishuConnectionMode:
      (feishu && (feishu as Record<string, unknown>).connection_mode === "webhook")
        ? "webhook"
        : "websocket",
    feishuAppId: String((feishu as Record<string, unknown> | null)?.app_id || "").trim(),
    feishuAppSecret: String((feishu as Record<string, unknown> | null)?.app_secret || "").trim(),
    feishuBotName: String((feishu as Record<string, unknown> | null)?.bot_name || "").trim(),
    feishuVerificationToken: String((feishu as Record<string, unknown> | null)?.verification_token || "").trim(),
    feishuDmPolicy:
      (feishu && typeof (feishu as Record<string, unknown>).dm_policy === "string"
        ? (feishu as Record<string, unknown>).dm_policy
        : "pairing") as ProviderFormState["feishuDmPolicy"],
    feishuAccountId: String((feishu as Record<string, unknown> | null)?.account_id || "main").trim() || "main",
  };
}

function mergeProviderForm(
  previous: ProviderFormState | undefined,
  provider: ProviderGuideProvider
): ProviderFormState {
  const defaults = createDefaultForm(provider);
  if (!previous) {
    return defaults;
  }

  return {
    ...defaults,
    selected: previous.selected,
    apiKey: previous.apiKey || defaults.apiKey,
    feishuAppSecret: previous.feishuAppSecret || defaults.feishuAppSecret,
    feishuVerificationToken:
      previous.feishuVerificationToken || defaults.feishuVerificationToken,
  };
}

export default function ProviderConfigGuide({
  variant = "page",
  onRequestClose,
  defaultOpen = true,
  autoOpen = false,
}: ProviderConfigGuideProps) {
  const [summary, setSummary] = useState<ProviderGuideSummary | null>(null);
  const [forms, setForms] = useState<Record<string, ProviderFormState>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [savingProviderId, setSavingProviderId] = useState("");
  const [refreshingProviderId, setRefreshingProviderId] = useState("");
  const [terminalBusyProviderId, setTerminalBusyProviderId] = useState("");
  const [activeTerminal, setActiveTerminal] = useState<ActiveTerminalState | null>(null);
  const [openclawConfigPath, setOpenclawConfigPath] = useState("");
  const [openclawConfigContent, setOpenclawConfigContent] = useState("");
  const [openclawConfigLoading, setOpenclawConfigLoading] = useState(false);
  const [openclawConfigSaving, setOpenclawConfigSaving] = useState(false);
  const [kiroCallbackUrl, setKiroCallbackUrl] = useState("");
  const [kiroCallbackSubmitting, setKiroCallbackSubmitting] = useState(false);
  const [kiroTerminalId, setKiroTerminalId] = useState<string | null>(null);
  const [kiroPhase, setKiroPhase] = useState<KiroPhase>("idle");
  const [open, setOpen] = useState(variant === "page" ? true : defaultOpen);
  const [activeProviderId, setActiveProviderId] = useState<string>("");

  const loadSummary = useCallback(async (preserveNotice = false) => {
    setLoading(true);
    const result = await caoRequest<ProviderGuideSummary>("GET", "/console/provider-config/summary");
    if (!result.ok) {
      setError(getCaoErrorHint(result, "读取 provider 配置摘要失败"));
      setLoading(false);
      return;
    }

    setSummary(result.data);
    setForms((previous: Record<string, ProviderFormState>) => {
      const next = { ...previous };
      for (const provider of result.data.providers) {
        next[provider.id] = mergeProviderForm(previous[provider.id], provider);
      }
      return next;
    });
    setActiveProviderId((prev) => {
      if (!prev && result.data.providers.length > 0) {
        return result.data.providers[0].id;
      }
      return prev;
    });
    setError("");
    if (!preserveNotice) {
      setNotice("");
    }
    if (variant === "modal" && autoOpen && result.data.should_show_guide) {
      setOpen(true);
    }
    setLoading(false);
  }, [autoOpen, variant]);

  useEffect(() => {
    const handle = window.setTimeout(() => {
      void loadSummary();
    }, 0);
    return () => window.clearTimeout(handle);
  }, [loadSummary]);

  function updateForm(providerId: string, patch: Partial<ProviderFormState>) {
    setForms((previous: Record<string, ProviderFormState>) => ({
      ...previous,
      [providerId]: {
        ...previous[providerId],
        ...patch,
      },
    }));
  }

  function updateProviderState(provider: ProviderGuideProvider) {
    setSummary((previous) => {
      if (!previous) {
        return previous;
      }
      return {
        ...previous,
        providers: previous.providers.map((item) =>
          item.id === provider.id ? provider : item
        ),
      };
    });
    setForms((previous: Record<string, ProviderFormState>) => ({
      ...previous,
      [provider.id]: mergeProviderForm(previous[provider.id], provider),
    }));
  }

  async function refreshProvider(providerId: string, preserveNotice = true) {
    setRefreshingProviderId(providerId);
    const result = await caoRequest<ProviderGuideProvider>(
      "GET",
      `/console/provider-config/providers/${providerId}`
    );
    setRefreshingProviderId("");
    if (!result.ok) {
      setError(getCaoErrorHint(result, "读取 provider 状态失败"));
      return;
    }

    updateProviderState(result.data);
    setError("");
    if (!preserveNotice) {
      setNotice("");
    }
  }

  const loadOpenClawConfigFile = useCallback(async () => {
    setOpenclawConfigLoading(true);
    const result = await caoRequest<{ provider_id: string; path: string; content: string }>(
      "GET",
      "/console/provider-config/openclaw/file"
    );
    setOpenclawConfigLoading(false);
    if (!result.ok) {
      setError(getCaoErrorHint(result, "读取 OpenClaw 配置文件失败"));
      return;
    }

    setOpenclawConfigPath(result.data.path || "");
    setOpenclawConfigContent(result.data.content || "");
    setError("");
  }, []);

  useEffect(() => {
    if (activeProviderId === "openclaw") {
      void loadOpenClawConfigFile();
    }
  }, [activeProviderId, loadOpenClawConfigFile]);

  async function dismissGuide() {
    await caoRequest("POST", "/console/provider-config/onboarding", {
      body: { dismissed: true },
    });
    setOpen(false);
    onRequestClose?.();
  }

  async function applyProviderConfiguration(provider: ProviderGuideProvider) {
    const form = forms[provider.id];
    if (!form) {
      return;
    }

    const payload: ProviderConfigApplyPayload = {
      provider_id: provider.id,
      mode: form.mode,
    };

    if (form.mode === "api") {
      payload.api_base_url = form.apiBaseUrl.trim();
      payload.api_key = form.apiKey.trim();
      payload.default_model = form.defaultModel.trim();
    }

    if (provider.id === "openclaw") {
      payload.compatibility = form.compatibility;
      if (form.feishuEnabled) {
        const feishuPayload: OpenClawFeishuConfigPayload = {
          enabled: true,
          domain: form.feishuDomain,
          connection_mode: form.feishuConnectionMode,
          app_id: form.feishuAppId.trim(),
          app_secret: form.feishuAppSecret.trim(),
          bot_name: form.feishuBotName.trim(),
          verification_token: form.feishuVerificationToken.trim() || undefined,
          dm_policy: form.feishuDmPolicy,
          account_id: form.feishuAccountId.trim() || "main",
        };
        payload.feishu = feishuPayload;
      }
    }

    setSavingProviderId(provider.id);
    setNotice("");
    setError("");

    const result = await caoRequest<ProviderConfigApplyResponse>("POST", "/console/provider-config/apply", {
      body: payload,
    });

    if (!result.ok) {
      setSavingProviderId("");
      setError(getCaoErrorHint(result, `保存 ${provider.label} 配置失败`));
      return;
    }

    setSavingProviderId("");
    setNotice(
      `${provider.label} 配置已保存${result.data.saved_path ? `，路径：${result.data.saved_path}` : ""}`
    );
    await refreshProvider(provider.id);
  }

  async function createShellTerminal(): Promise<string | null> {
    const result = await caoRequest<{ ok: boolean; terminal_id: string; session_name: string }>(
      "POST",
      "/console/terminals/shell",
      { body: {} }
    );
    if (!result.ok || !result.data.terminal_id) {
      setError(getCaoErrorHint(result, "创建登录终端失败"));
      return null;
    }
    return result.data.terminal_id;
  }

  async function sendAgentInput(terminalId: string, message: string) {
    return caoRequest("POST", `/console/agents/${terminalId}/input`, {
      body: { message },
    });
  }

  async function delay(ms: number) {
    await new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  async function destroyTerminal(terminalId: string) {
    const result = await caoRequest<{ success?: boolean }>("DELETE", `/terminals/${terminalId}`);
    if (!result.ok) {
      setError(getCaoErrorHint(result, "关闭登录终端失败"));
    }
  }

  async function openOpenClawConfigureTerminal(provider: ProviderGuideProvider) {
    setTerminalBusyProviderId(provider.id);
    setError("");
    const terminalId = await createShellTerminal();
    if (!terminalId) {
      setTerminalBusyProviderId("");
      return;
    }

    const command = "openclaw onboard";
    const sendResult = await sendAgentInput(terminalId, command);
    if (!sendResult.ok) {
      await destroyTerminal(terminalId);
      setTerminalBusyProviderId("");
      setError(getCaoErrorHint(sendResult, "启动 OpenClaw 配置终端失败"));
      return;
    }

    setActiveTerminal({
      terminalId,
      providerId: provider.id,
      action: "configure",
      title: "OpenClaw 配置终端",
      subtitle: `已执行：${command}`,
    });
    setTerminalBusyProviderId("");
  }

  async function saveOpenClawConfigFile() {
    setOpenclawConfigSaving(true);
    setError("");
    const result = await caoRequest<{
      provider_id: string;
      path: string;
      content: string;
      gateway?: { command?: string; stdout?: string; stderr?: string };
    }>("PUT", "/console/provider-config/openclaw/file", {
      body: { content: openclawConfigContent },
    });
    setOpenclawConfigSaving(false);
    if (!result.ok) {
      setError(getCaoErrorHint(result, "保存 OpenClaw 配置文件失败"));
      return;
    }

    setOpenclawConfigPath(result.data.path || openclawConfigPath);
    setOpenclawConfigContent(result.data.content || openclawConfigContent);
    await refreshProvider("openclaw");
    setNotice(
      `OpenClaw 配置文件已保存，网关已自动重启${
        result.data.gateway?.command ? `（${result.data.gateway.command}）` : ""
      }`
    );
  }

  async function runProviderTerminalAction(
    provider: ProviderGuideProvider,
    action: "login" | "logout"
  ) {
    const viaConsole =
      action === "login"
        ? Boolean(provider.login_via_console)
        : Boolean(provider.logout_via_console);
    const launchCommand = viaConsole
      ? provider.console_command || provider.command || ""
      : action === "login"
      ? provider.login_command || ""
      : provider.logout_command || "";
    const followupCommand = viaConsole
      ? action === "login"
        ? provider.login_command || ""
        : provider.logout_command || ""
      : "";

    if (!launchCommand) {
      setError(
        action === "login"
          ? `${provider.label} 没有可用的登录命令`
          : `${provider.label} 当前未探测到 logout 命令`
      );
      return;
    }

    setTerminalBusyProviderId(provider.id);
    setError("");
    const terminalId = await createShellTerminal();
    if (!terminalId) {
      setTerminalBusyProviderId("");
      return;
    }

    const sendResult = await sendAgentInput(terminalId, launchCommand);
    if (!sendResult.ok) {
      await destroyTerminal(terminalId);
      setTerminalBusyProviderId("");
      setError(
        getCaoErrorHint(
          sendResult,
          `${action === "login" ? "启动" : "执行"} ${provider.label}${action === "login" ? " 登录" : " 退出"}终端失败`
        )
      );
      return;
    }

    if (viaConsole && followupCommand) {
      await delay(1200);
      const followupResult = await sendAgentInput(terminalId, followupCommand);
      if (!followupResult.ok) {
        await destroyTerminal(terminalId);
        setTerminalBusyProviderId("");
        setError(
          getCaoErrorHint(
            followupResult,
            `发送 ${provider.label} ${followupCommand} 指令失败`
          )
        );
        return;
      }
    }

    const terminalState: ActiveTerminalState = {
      terminalId,
      providerId: provider.id,
      action,
      title: `${provider.label}${action === "login" ? " 登录" : " 退出"}终端`,
      subtitle: viaConsole
        ? `已执行：${launchCommand} -> ${followupCommand}`
        : `已执行：${launchCommand}`,
    };

    if (provider.id === "kiro_cli" && action === "login") {
      setKiroTerminalId(terminalId);
      setKiroPhase("waiting_callback");
    }

    setActiveTerminal(terminalState);
    setTerminalBusyProviderId("");
  }

  async function submitKiroCallback() {
    if (!kiroCallbackUrl.trim()) {
      setError("请输入完整回调地址");
      return;
    }
    setKiroCallbackSubmitting(true);
    setError("");
    const result = await caoRequest<{ ok: boolean; status_code: number; body: string }>(
      "POST",
      "/console/provider-config/kiro/callback",
      { body: { callback_url: kiroCallbackUrl.trim() } }
    );
    setKiroCallbackSubmitting(false);
    if (!result.ok) {
      setError(getCaoErrorHint(result, "执行 Kiro 回调失败"));
      return;
    }
    setNotice(`Kiro 回调请求已发送，HTTP ${result.data.status_code}`);
    setKiroCallbackUrl("");
    setKiroPhase("callback_submitted");
    // Re-open the original Kiro terminal to check login status
    if (kiroTerminalId) {
      setActiveTerminal({
        terminalId: kiroTerminalId,
        providerId: "kiro_cli",
        action: "login",
        title: "Kiro 登录状态终端",
        subtitle: "回调已发送，请在终端中确认登录状态后关闭",
      });
    }
    await refreshProvider("kiro_cli");
  }

  /** Handle terminal drawer button click */
  async function handleTerminalClose() {
    if (
      activeTerminal?.providerId === "kiro_cli" &&
      activeTerminal.action === "login" &&
      kiroPhase === "waiting_callback"
    ) {
      // Minimize only: hide the drawer but preserve the Kiro terminal session
      setActiveTerminal(null);
    } else {
      // Full destroy: clear all terminal state
      const terminalToDestroy = activeTerminal;
      setActiveTerminal(null);
      if (terminalToDestroy) {
        await destroyTerminal(terminalToDestroy.terminalId);
        await refreshProvider(terminalToDestroy.providerId);
      }
      if (terminalToDestroy?.providerId === "kiro_cli") {
        setKiroTerminalId(null);
        setKiroPhase("idle");
      }
    }
  }

  /** Re-open the persisted Kiro terminal drawer */
  function reopenKiroTerminal() {
    if (!kiroTerminalId) return;
    const kiroProvider = summary?.providers.find((p) => p.id === "kiro_cli");
    const title =
      kiroPhase === "callback_submitted"
        ? "Kiro 登录状态终端"
        : `${kiroProvider?.label ?? "Kiro"} 登录终端`;
    const subtitle =
      kiroPhase === "callback_submitted"
        ? "回调已发送，请在终端中确认登录状态后关闭"
        : "等待浏览器完成认证回调...";
    setActiveTerminal({
      terminalId: kiroTerminalId,
      providerId: "kiro_cli",
      action: "login",
      title,
      subtitle,
    });
  }

  // Whether the terminal drawer can be fully closed (vs only minimized)
  const terminalCanClose =
    !(activeTerminal?.providerId === "kiro_cli" && activeTerminal.action === "login") ||
    kiroPhase !== "waiting_callback";

  // Provider tab helpers
  const allProviders = summary?.providers ?? [];
  const activeProvider =
    allProviders.find((p) => p.id === activeProviderId) ?? allProviders[0] ?? null;

  // Per-provider right-panel rendering
  function renderProviderContent(provider: ProviderGuideProvider) {
    const form = forms[provider.id] || createDefaultForm(provider);
    const isSaving = savingProviderId === provider.id;
    const isRefreshing = refreshingProviderId === provider.id;
    const isTerminalBusy = terminalBusyProviderId === provider.id;
    const status = provider.status;
    const isApiMode = provider.supports_api_config && form.mode === "api";
    const showAccountLogin =
      provider.supports_account_login &&
      (!provider.supports_api_config || form.mode === "account");
    const shouldShowModeSwitch =
      provider.supports_api_config && DEFAULT_ACCOUNT_MODE_PROVIDER_IDS.has(provider.id);
    const isKiro = provider.id === "kiro_cli";
    const kiroTerminalHidden = isKiro && kiroTerminalId && !activeTerminal;
    const canLogin = Boolean(provider.login_command) && Boolean(provider.login_supported) && status.installed;
    const canLogout = Boolean(provider.logout_command) && Boolean(provider.logout_supported) && status.installed;
    const showLogoutAction = showAccountLogin && status.configured;

    return (
      <div style={{ display: "grid", gap: 14 }}>
        {/* Provider header: name + status + mode switch */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            gap: 12,
            flexWrap: "wrap",
            alignItems: "flex-start",
          }}
        >
          <div style={{ display: "grid", gap: 6 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <SectionTitle title={provider.label} />
              <StatusPill
                text={status.installed ? "已安装" : "未安装"}
                active={status.installed}
              />
              <StatusPill
                text={status.configured ? "已配置" : "待配置"}
                active={status.configured}
              />
              {status.detected_mode ? (
                <StatusPill text={`当前: ${status.detected_mode}`} active />
              ) : null}
            </div>
            <div style={{ color: "var(--text-dim)", fontSize: 12 }}>
              命令：{provider.command}
              {status.settings_path ? ` · 配置路径：${status.settings_path}` : ""}
            </div>
            {status.details ? <InfoHint text={status.details} /> : null}
          </div>

          {/* Mode switch buttons */}
          {shouldShowModeSwitch ? (
            <div style={{ display: "flex", gap: 6, alignItems: "center", flexShrink: 0 }}>
              <SecondaryButton
                type="button"
                onClick={() => updateForm(provider.id, { mode: "account" })}
                style={{
                  padding: "6px 12px",
                  background:
                    form.mode === "account" ? "var(--surface)" : "var(--surface2)",
                  fontWeight: form.mode === "account" ? 700 : 500,
                  border:
                    form.mode === "account"
                      ? "1.5px solid var(--accent)"
                      : undefined,
                }}
              >
                账号登录
              </SecondaryButton>
              <SecondaryButton
                type="button"
                onClick={() => updateForm(provider.id, { mode: "api" })}
                style={{
                  padding: "6px 12px",
                  background:
                    form.mode === "api" ? "var(--surface)" : "var(--surface2)",
                  fontWeight: form.mode === "api" ? 700 : 500,
                  border:
                    form.mode === "api"
                      ? "1.5px solid var(--accent)"
                      : undefined,
                }}
              >
                API Key
              </SecondaryButton>
            </div>
          ) : null}
        </div>

        {/* API Key mode */}
        {isApiMode ? (
          <SectionCard>
            <div style={{ display: "grid", gap: 10 }}>
              {provider.id === "openclaw" ? (
                <>
                  <InfoHint text="OpenClaw 现在通过终端执行 openclaw onboard 启动配置向导；下方编辑器可直接修改配置文件，保存后会自动重启 gateway。" />
                  <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                    <PrimaryButton
                      type="button"
                      onClick={() => void openOpenClawConfigureTerminal(provider)}
                      disabled={isTerminalBusy}
                    >
                      {isTerminalBusy ? "启动中..." : "打开配置终端"}
                    </PrimaryButton>
                    <SecondaryButton
                      type="button"
                      onClick={() => void loadOpenClawConfigFile()}
                      disabled={openclawConfigLoading}
                    >
                      {openclawConfigLoading ? "加载中..." : "重新加载配置文件"}
                    </SecondaryButton>
                    <SecondaryButton
                      type="button"
                      onClick={() => void refreshProvider(provider.id)}
                      disabled={isRefreshing}
                    >
                      {isRefreshing ? "刷新中..." : "刷新状态"}
                    </SecondaryButton>
                  </div>
                  <div
                    style={{
                      display: "grid",
                      gap: 8,
                      marginTop: 4,
                      padding: 12,
                      border: "1px solid var(--border)",
                      borderRadius: 10,
                      background: "var(--surface2)",
                    }}
                  >
                    <div style={{ color: "var(--text-bright)", fontWeight: 700 }}>
                      配置文件{openclawConfigPath ? `：${openclawConfigPath}` : ""}
                    </div>
                    <CodeEditorInput
                      value={openclawConfigContent}
                      onChange={setOpenclawConfigContent}
                      language="javascript"
                      fileName={openclawConfigPath || "openclaw.json"}
                      showToolbar
                      enableFormat
                      maxHeight={420}
                      placeholder="正在加载 OpenClaw 配置文件..."
                    />
                    <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                      <PrimaryButton
                        type="button"
                        onClick={() => void saveOpenClawConfigFile()}
                        disabled={openclawConfigSaving || openclawConfigLoading}
                      >
                        {openclawConfigSaving ? "保存并重启中..." : "保存配置并重启网关"}
                      </PrimaryButton>
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
                      gap: 10,
                    }}
                  >
                    <div style={{ display: "grid", gap: 6 }}>
                      <div style={{ color: "var(--text-dim)", fontSize: 12 }}>API Base URL</div>
                      <TextInput
                        value={form.apiBaseUrl}
                        onChange={(event: ChangeEvent<HTMLInputElement>) =>
                          updateForm(provider.id, { apiBaseUrl: event.target.value })
                        }
                        placeholder="例如 https://api.openai.com/v1"
                      />
                    </div>
                    <div style={{ display: "grid", gap: 6 }}>
                      <div style={{ color: "var(--text-dim)", fontSize: 12 }}>默认模型</div>
                      <TextInput
                        value={form.defaultModel}
                        onChange={(event: ChangeEvent<HTMLInputElement>) =>
                          updateForm(provider.id, { defaultModel: event.target.value })
                        }
                        placeholder={
                          provider.id === "claude_code" ? "claude-sonnet-4-6" : "gpt-5.3-codex"
                        }
                      />
                    </div>
                  </div>
                  <div style={{ display: "grid", gap: 6 }}>
                    <div style={{ color: "var(--text-dim)", fontSize: 12 }}>API Key</div>
                    <TextInput
                      type="password"
                      value={form.apiKey}
                      onChange={(event: ChangeEvent<HTMLInputElement>) =>
                        updateForm(provider.id, { apiKey: event.target.value })
                      }
                      placeholder="输入 provider 对应的 API Key"
                    />
                  </div>
                </>
              )}

              {provider.id === "openclaw" ? null : (
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  <PrimaryButton
                    type="button"
                    onClick={() => void applyProviderConfiguration(provider)}
                    disabled={isSaving}
                  >
                    {isSaving ? "保存中..." : "保存 API 配置"}
                  </PrimaryButton>
                  <SecondaryButton
                    type="button"
                    onClick={() => void refreshProvider(provider.id)}
                    disabled={isRefreshing}
                  >
                    {isRefreshing ? "刷新中..." : "刷新状态"}
                  </SecondaryButton>
                </div>
              )}
            </div>
          </SectionCard>
        ) : null}

        {/* Account login mode */}
        {showAccountLogin ? (
          <SectionCard>
            <div style={{ display: "grid", gap: 10 }}>
              <InfoHint
                text={
                  isKiro
                    ? "Kiro 登录会直接执行 kiro-cli login；浏览器完成认证后若回调无法自动到达容器，请将完整 callback URL 粘贴到下方并点击确认，由容器内发起请求。"
                    : provider.id === "copilot"
                    ? "Copilot 会在打开终端后直接执行 copilot login 进入 device flow。"
                    : `点击${showLogoutAction ? "退出" : "登录"}后会打开终端并直接执行 ${
                        showLogoutAction
                          ? provider.logout_via_console
                            ? `${provider.console_command || provider.command} -> ${provider.logout_command || "logout"}`
                            : provider.logout_command || "logout"
                          : provider.login_via_console
                          ? `${provider.console_command || provider.command} -> ${provider.login_command || "login"}`
                          : provider.login_command || "login"
                      }。`
                }
              />
              {showLogoutAction && !canLogout ? (
                <InfoHint text="当前 CLI 未探测到 logout 子命令，暂不提供退出操作。" />
              ) : null}

              {/* Kiro: phase status banner */}
              {isKiro && kiroPhase !== "idle" ? (
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 10,
                    padding: "8px 12px",
                    borderRadius: 8,
                    background: "var(--surface2)",
                    border: "1px solid var(--border)",
                    fontSize: 13,
                  }}
                >
                  <span
                    style={{
                      color:
                        kiroPhase === "callback_submitted"
                          ? "var(--success)"
                          : "var(--accent)",
                    }}
                  >
                    {kiroPhase === "waiting_callback"
                      ? "⏳ 等待浏览器回调..."
                      : "✓ 回调已发送，请在终端中确认登录状态"}
                  </span>
                  {kiroTerminalHidden ? (
                    <SecondaryButton
                      type="button"
                      onClick={reopenKiroTerminal}
                      style={{ padding: "4px 10px", marginLeft: "auto" }}
                    >
                      查看终端
                    </SecondaryButton>
                  ) : null}
                </div>
              ) : null}

              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                {!isKiro || kiroPhase === "idle" ? (
                  <PrimaryButton
                    type="button"
                    onClick={() =>
                      void runProviderTerminalAction(
                        provider,
                        showLogoutAction ? "logout" : "login"
                      )
                    }
                    disabled={isTerminalBusy || (showLogoutAction ? !canLogout : !canLogin)}
                  >
                    {isTerminalBusy
                      ? "启动中..."
                      : showLogoutAction
                      ? "退出"
                      : "登录"}
                  </PrimaryButton>
                ) : null}
                <SecondaryButton
                  type="button"
                  onClick={() => void refreshProvider(provider.id)}
                  disabled={isRefreshing}
                >
                  {isRefreshing ? "刷新中..." : "刷新状态"}
                </SecondaryButton>
              </div>

              {/* Kiro callback section */}
              {isKiro ? (
                <div
                  style={{
                    display: "grid",
                    gap: 10,
                    marginTop: 6,
                    borderTop: "1px dashed var(--border)",
                    paddingTop: 12,
                  }}
                >
                  <div style={{ color: "var(--text-bright)", fontWeight: 700, fontSize: 14 }}>
                    Kiro 回调补偿
                  </div>
                  <InfoHint text="浏览器完成认证后，若终端未自动登录，请将浏览器地址栏中的完整 callback URL 粘贴到下方，由容器内发起 GET 请求完成登录。" />
                  {kiroPhase === "idle" ? (
                    <div style={{ color: "var(--text-dim)", fontSize: 12 }}>
                      请先点击「登录」并在浏览器完成认证后，再填写回调地址。
                    </div>
                  ) : (
                    <>
                      <TextInput
                        value={kiroCallbackUrl}
                        onChange={(event: ChangeEvent<HTMLInputElement>) =>
                          setKiroCallbackUrl(event.target.value)
                        }
                        placeholder="粘贴完整 callback URL，例如 http://localhost:49153/..."
                      />
                      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                        <PrimaryButton
                          type="button"
                          onClick={() => void submitKiroCallback()}
                          disabled={kiroCallbackSubmitting || !kiroCallbackUrl.trim()}
                        >
                          {kiroCallbackSubmitting
                            ? "提交中..."
                            : "确认回调并查看登录状态"}
                        </PrimaryButton>
                      </div>
                    </>
                  )}
                </div>
              ) : null}
            </div>
          </SectionCard>
        ) : null}
      </div>
    );
  }

  // Left tab list
  function renderTabList() {
    return (
      <div
        style={{
          width: 180,
          flexShrink: 0,
          borderRight: "1px solid var(--border)",
          display: "flex",
          flexDirection: "column",
          gap: 2,
          paddingRight: 2,
        }}
      >
        {allProviders.map((provider) => {
          const isActive = provider.id === (activeProvider?.id ?? "");
          const s = provider.status;
          return (
            <button
              key={provider.id}
              type="button"
              onClick={() => setActiveProviderId(provider.id)}
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 4,
                padding: "10px 12px",
                borderRadius: 8,
                background: isActive ? "var(--surface2)" : "transparent",
                border: isActive ? "1px solid var(--border)" : "1px solid transparent",
                cursor: "pointer",
                textAlign: "left",
                color: isActive ? "var(--text-bright)" : "var(--text)",
                fontWeight: isActive ? 700 : 400,
                transition: "background 0.15s",
              }}
            >
              <span
                style={{
                  fontSize: 13,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {provider.label}
              </span>
              <span style={{ display: "flex", gap: 4 }}>
                <span
                  style={{
                    fontSize: 10,
                    color: s.installed ? "var(--success)" : "var(--text-dim)",
                  }}
                >
                  {s.installed ? "✓ 已安装" : "✗ 未安装"}
                </span>
                {s.configured ? (
                  <span style={{ fontSize: 10, color: "var(--success)" }}>· 已配置</span>
                ) : null}
              </span>
            </button>
          );
        })}
      </div>
    );
  }

  // Main body content (tab layout)
  const bodyContent = loading ? (
    <div style={{ color: "var(--text-dim)", padding: 16 }}>正在读取 provider 状态...</div>
  ) : !summary ? (
    <EmptyState text="未能读取 provider 配置摘要" />
  ) : (
    <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
      {renderTabList()}
      <div style={{ flex: 1, minWidth: 0 }}>
        {activeProvider ? renderProviderContent(activeProvider) : null}
      </div>
    </div>
  );

  const content = (
    <>
      <PageIntro
        title="Provider 配置引导"
        description="覆盖安装脚本中已接入的 provider。首次进入会自动弹出，之后可通过导航栏的配置按钮再次打开。"
      />
      {error && <ErrorBanner text={error} />}
      {notice ? (
        <div
          style={{
            color: "var(--success)",
            border: "1px solid var(--success)",
            background: "var(--surface)",
            borderRadius: 10,
            padding: "8px 10px",
            fontSize: 13,
          }}
        >
          {notice}
        </div>
      ) : null}
      {bodyContent}
    </>
  );

  if (variant === "page") {
    return (
      <>
        <PageShell>{content}</PageShell>
        {activeTerminal ? (
          <TerminalDrawer
            terminalId={activeTerminal.terminalId}
            title={activeTerminal.title}
            subtitle={activeTerminal.subtitle}
            onClose={() => {
              void handleTerminalClose();
            }}
            canClose={terminalCanClose}
          />
        ) : null}
      </>
    );
  }

  const containerStyle =
    variant === "modal"
      ? {
          position: "fixed" as const,
          inset: 0,
          background: "rgba(2, 6, 23, 0.58)",
          display: open ? "flex" : "none",
          alignItems: "center",
          justifyContent: "center",
          padding: 18,
          zIndex: 60,
        }
      : undefined;

  return (
    <>
      {containerStyle ? (
        <div style={containerStyle} onClick={() => void dismissGuide()}>
          <div
            onClick={(event) => event.stopPropagation()}
            style={{
              width: "min(1080px, 100%)",
              maxHeight: "calc(100vh - 36px)",
              overflow: "auto",
              background: "var(--surface)",
              border: "1px solid var(--border)",
              borderRadius: 16,
              padding: 18,
              boxShadow: "0 20px 60px rgba(0,0,0,0.35)",
            }}
          >
            <div
              style={{ display: "flex", justifyContent: "space-between", gap: 12, marginBottom: 8 }}
            >
              <div style={{ color: "var(--text-dim)", fontSize: 12 }}>
                首次进入控制台，默认弹出 provider 配置引导。
              </div>
              <SecondaryButton
                type="button"
                onClick={() => void dismissGuide()}
                style={{ padding: "6px 10px" }}
              >
                关闭引导
              </SecondaryButton>
            </div>
            {content}
          </div>
        </div>
      ) : null}

      {activeTerminal ? (
        <TerminalDrawer
          terminalId={activeTerminal.terminalId}
          title={activeTerminal.title}
          subtitle={activeTerminal.subtitle}
          onClose={() => {
            void handleTerminalClose();
          }}
          canClose={terminalCanClose}
        />
      ) : null}
    </>
  );
}

export type HttpMethod = "GET" | "POST" | "DELETE" | "PUT" | "PATCH";

export interface ApiResponse<T> {
  ok: boolean;
  status: number;
  data: T;
}

type ErrorLikePayload = {
  detail?: unknown;
  message?: unknown;
};

async function parseResponseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response.text();
}

function resolveControlPanelBaseUrl(): string {
  const fromEnv = process.env.NEXT_PUBLIC_CAO_CONTROL_PANEL_URL?.trim();
  if (fromEnv) {
    return fromEnv.replace(/\/$/, "");
  }

  if (window.location.port === "3000") {
    return "http://localhost:8000";
  }

  return window.location.origin;
}

function resolveControlPanelBaseUrlCandidates(): string[] {
  const fromEnv = process.env.NEXT_PUBLIC_CAO_CONTROL_PANEL_URL?.trim();
  if (fromEnv) {
    return [fromEnv.replace(/\/$/, "")];
  }

  if (window.location.port === "3000") {
    return [
      "http://localhost:8000",
      "http://127.0.0.1:8000",
      window.location.origin,
    ];
  }

  return [window.location.origin, "http://localhost:8000", "http://127.0.0.1:8000"];
}

function resolveApiPath(path: string): string {
  if (path.startsWith("/console") || path.startsWith("/auth")) {
    return path;
  }
  return `/api${path}`;
}

export async function caoRequest<T = unknown>(
  method: HttpMethod,
  path: string,
  options?: {
    query?: Record<string, string | number | undefined | null>;
    body?: unknown;
  }
): Promise<ApiResponse<T>> {
  const normalizedPath = resolveApiPath(path);
  const baseCandidates = resolveControlPanelBaseUrlCandidates();
  const baseUrl = resolveControlPanelBaseUrl();
  const deduplicatedBaseUrls = Array.from(new Set([baseUrl, ...baseCandidates]));
  let lastErrorMessage = "";

  for (const candidate of deduplicatedBaseUrls) {
    const url = new URL(normalizedPath, `${candidate}/`);

    if (options?.query) {
      Object.entries(options.query).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== "") {
          url.searchParams.set(key, String(value));
        }
      });
    }

    try {
      const response = await fetch(url.toString(), {
        method,
        credentials: "include",
        headers: {
          "Content-Type": "application/json",
        },
        body: options?.body ? JSON.stringify(options.body) : undefined,
        cache: "no-store",
      });

      const data = (await parseResponseBody(response)) as T;
      return {
        ok: response.ok,
        status: response.status,
        data,
      };
    } catch (error) {
      lastErrorMessage = String(error);
    }
  }

  return {
    ok: false,
    status: 0,
    data: {
      detail: `Network request failed: ${lastErrorMessage || "unknown error"}`,
      path,
      tried_base_urls: deduplicatedBaseUrls,
    } as T,
  };
}

export function getCaoErrorHint(result: ApiResponse<unknown>, fallback: string): string {
  if (result.status === 0) {
    return `${fallback}：无法连接到控制面板服务，请确认 cao-control-panel 已启动（默认 http://localhost:8000）`;
  }

  const payload = result.data as ErrorLikePayload | undefined;
  const detail = payload?.detail;
  if (typeof detail === "string" && detail.trim()) {
    return `${fallback}：${detail}`;
  }

  const message = payload?.message;
  if (typeof message === "string" && message.trim()) {
    return `${fallback}：${message}`;
  }

  return fallback;
}

export interface ConsoleAgent {
  id: string;
  alias?: string;
  name?: string;
  provider?: string;
  session_name?: string;
  agent_profile?: string;
  status?: string;
  is_main?: boolean;
  is_offline?: boolean;
  last_active?: string;
}

export interface ConsoleOverview {
  uptime_seconds: number;
  agents_total: number;
  main_agents_total: number;
  worker_agents_total: number;
  provider_counts: Record<string, number>;
  status_counts: Record<string, number>;
  profile_counts: Record<string, number>;
  main_agents: ConsoleAgent[];
  teams?: ConsoleTaskTeam[];
  team_leaders?: ConsoleAgent[];
}

export interface ConsoleLeaderGroup {
  leader: ConsoleAgent;
  team_alias?: string;
  team_working_directory?: string;
  members: ConsoleAgent[];
}

export interface ConsoleOrganization {
  leaders_total: number;
  workers_total: number;
  leaders: ConsoleAgent[];
  workers: ConsoleAgent[];
  leader_groups: ConsoleLeaderGroup[];
  unassigned_workers: ConsoleAgent[];
}

export interface ConsoleEnsureOnlineResponse {
  ok: boolean;
  restored: boolean;
  leader_id: string;
  terminal_id: string;
  session_name: string;
  leader: ConsoleAgent;
}

export interface ConsoleShellTerminalResponse {
  ok: boolean;
  terminal_id: string;
  session_name: string;
  provider: string;
  working_directory?: string | null;
}

export interface ConsoleAssetTeam {
  leader_id: string;
  team_name: string;
  working_directory: string;
  leader: ConsoleAgent;
}

export interface ConsoleAssetTeamsResponse {
  teams: ConsoleAssetTeam[];
}

export interface ConsoleAssetEntry {
  name: string;
  path: string;
  is_dir: boolean;
  size?: number | null;
  modified_at?: string;
}

export interface ConsoleAssetTreeResponse {
  leader_id: string;
  working_directory: string;
  path: string;
  entries: ConsoleAssetEntry[];
}

export interface ConsoleAssetFileResponse {
  leader_id: string;
  working_directory: string;
  path: string;
  file_path: string;
  content: string;
}

export interface ConsoleHomeDirectoryItem {
  name: string;
  path: string;
}

export interface ConsoleHomeWorkdirsResponse {
  home_directory: string;
  directories: ConsoleHomeDirectoryItem[];
}

export interface ConsoleAgentProfileOption {
  profile: string;
  display_name?: string | null;
}

export interface ConsoleAgentProfilesResponse {
  profiles: string[];
  profile_options?: ConsoleAgentProfileOption[];
}

export interface CreateAgentProfileRequest {
  name: string;
  description?: string;
  system_prompt?: string;
  content?: string;
  provider?: string;
  display_name?: string;
}

export interface CreateAgentProfileResponse {
  ok: boolean;
  profile: string;
  file_path: string;
}

export interface AgentProfileFileResponse {
  profile: string;
  file_name?: string;
  file_path: string;
  content: string;
  display_name?: string;
}

export interface ConsoleAgentProfileFileItem {
  file_name: string;
  profile: string;
  file_path: string;
  display_name?: string;
}

export interface ConsoleAgentProfileFilesResponse {
  files: ConsoleAgentProfileFileItem[];
}

export interface UpdateAgentProfileResponse {
  ok: boolean;
  profile: string;
  file_path: string;
}

export interface InstallAgentProfileResponse {
  ok: boolean;
  profile: string;
  command: string;
  return_code: number;
  stdout: string;
  stderr: string;
}

export interface ConsoleTaskInstantItem {
  terminal_id: string;
  session_name?: string;
  agent_profile?: string;
  task_title?: string;
  status?: string;
  last_active?: string;
}

export interface ConsoleTaskScheduledItem {
  name: string;
  display_name?: string | null;
  file_path: string;
  schedule: string;
  agent_profile: string;
  provider: string;
  script?: string;
  session_name?: string;
  enabled: boolean;
  last_run?: string | null;
  next_run?: string | null;
}

export interface ConsoleTaskTeam {
  leader: ConsoleAgent;
  team_alias?: string;
  members: ConsoleAgent[];
  instant_tasks: ConsoleTaskInstantItem[];
  scheduled_tasks: ConsoleTaskScheduledItem[];
}

export interface ConsoleTasksResponse {
  teams: ConsoleTaskTeam[];
  unassigned_scheduled_tasks: ConsoleTaskScheduledItem[];
}

export interface ConsoleScheduledTaskFile {
  file_name: string;
  flow_name: string;
  display_name?: string | null;
  file_path: string;
}

export interface ConsoleScheduledTaskFilesResponse {
  files: ConsoleScheduledTaskFile[];
}

export interface ProviderGuideStatus {
  installed: boolean;
  configured: boolean;
  detected_mode?: string | null;
  details?: string;
  settings_path?: string | null;
}

export interface ProviderGuideSavedSettings {
  mode?: string;
  api_base_url?: string | null;
  api_key?: string | null;
  default_model?: string | null;
  compatibility?: string | null;
  login_completed_at?: string | null;
  feishu?: Record<string, unknown> | null;
  updated_at?: string | null;
}

export interface ProviderGuideProvider {
  id: string;
  label: string;
  command: string;
  supports_account_login: boolean;
  supports_api_config: boolean;
  default_selected: boolean;
  console_command?: string | null;
  login_command?: string | null;
  logout_command?: string | null;
  login_via_console?: boolean;
  logout_via_console?: boolean;
  login_supported?: boolean;
  logout_supported?: boolean;
  status: ProviderGuideStatus;
  saved_settings: ProviderGuideSavedSettings;
}

export interface ProviderGuideSummary {
  should_show_guide: boolean;
  onboarding: {
    dismissed?: boolean;
    dismissed_at?: string | null;
    completed_at?: string | null;
  };
  providers: ProviderGuideProvider[];
}

export interface OpenClawFeishuConfigPayload {
  enabled: boolean;
  domain: "feishu" | "lark";
  connection_mode: "websocket" | "webhook";
  app_id?: string;
  app_secret?: string;
  bot_name?: string;
  verification_token?: string;
  dm_policy: "pairing" | "allowlist" | "open" | "disabled";
  account_id: string;
}

export interface ProviderConfigApplyPayload {
  provider_id: string;
  mode: "account" | "api";
  api_base_url?: string;
  api_key?: string;
  default_model?: string;
  compatibility?: "openai" | "anthropic";
  feishu?: OpenClawFeishuConfigPayload;
}

export interface ProviderConfigApplyResponse {
  ok: boolean;
  provider_id: string;
  saved_path?: string | null;
  command?: string | null;
  settings?: ProviderGuideSavedSettings;
}

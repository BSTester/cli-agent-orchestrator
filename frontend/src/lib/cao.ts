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

export interface ConsoleHomeDirectoryItem {
  name: string;
  path: string;
}

export interface ConsoleHomeWorkdirsResponse {
  home_directory: string;
  directories: ConsoleHomeDirectoryItem[];
}

export interface ConsoleAgentProfilesResponse {
  profiles: string[];
}

export interface CreateAgentProfileRequest {
  name: string;
  description?: string;
  system_prompt?: string;
  content?: string;
  provider?: string;
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
}

export interface ConsoleAgentProfileFileItem {
  file_name: string;
  profile: string;
  file_path: string;
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
  file_path: string;
  schedule: string;
  agent_profile: string;
  provider: string;
  script?: string;
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
  file_path: string;
}

export interface ConsoleScheduledTaskFilesResponse {
  files: ConsoleScheduledTaskFile[];
}

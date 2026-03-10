"use strict";

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function asTextResult(payload) {
  return {
    content: [
      {
        type: "text",
        text: typeof payload === "string" ? payload : JSON.stringify(payload),
      },
    ],
  };
}

function getPluginCfg(api) {
  const cfg = api.pluginConfig || {};
  const baseUrl = String(
    cfg.baseUrl || process.env.CAO_SERVER_URL || process.env.CAO_API_BASE_URL || "http://localhost:9889",
  ).replace(/\/$/, "");

  return {
    baseUrl,
    defaultProvider: String(cfg.defaultProvider || "openclaw"),
    requestTimeoutMs: Number(cfg.requestTimeoutMs || 15000),
    senderTerminalId: cfg.senderTerminalId ? String(cfg.senderTerminalId) : "",
  };
}

function resolveRequiredTerminalId(value, fieldName) {
  const resolved = String(value || "").trim();
  if (!resolved) {
    throw new Error(`Missing required parameter: ${fieldName}`);
  }
  return resolved;
}

async function requestJson(api, method, path, params) {
  const cfg = getPluginCfg(api);
  const url = new URL(`${cfg.baseUrl}${path}`);

  if (params && typeof params === "object") {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === null) {
        continue;
      }
      const text = String(value);
      if (!text.length) {
        continue;
      }
      url.searchParams.set(key, text);
    }
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), cfg.requestTimeoutMs);

  try {
    const response = await fetch(url.toString(), {
      method,
      signal: controller.signal,
    });

    const bodyText = await response.text();
    let body;
    try {
      body = bodyText ? JSON.parse(bodyText) : {};
    } catch {
      body = { raw: bodyText };
    }

    if (!response.ok) {
      throw new Error(`${method} ${path} failed (${response.status}): ${bodyText}`);
    }

    return body;
  } finally {
    clearTimeout(timer);
  }
}

function normalizeStatus(status) {
  return String(status || "").trim().toLowerCase();
}

async function waitTerminalReady(api, terminalId, timeoutSeconds) {
  const deadline = Date.now() + timeoutSeconds * 1000;
  while (Date.now() < deadline) {
    const detail = await requestJson(api, "GET", `/terminals/${terminalId}`);
    const status = normalizeStatus(detail.status);
    if (status === "idle" || status === "completed") {
      return true;
    }
    await sleep(1000);
  }
  return false;
}

async function findOrCreateWorker(api, options) {
  const cfg = getPluginCfg(api);
  const currentTerminalId = options.currentTerminalId;
  const currentMeta = await requestJson(api, "GET", `/terminals/${currentTerminalId}`);
  const sessionName = currentMeta.session_name;
  const provider = options.provider || cfg.defaultProvider;

  const terminals = await requestJson(api, "GET", `/sessions/${sessionName}/terminals`);
  const reuse = Array.isArray(terminals)
    ? terminals.find(
        (item) =>
          item &&
          item.id !== currentTerminalId &&
          item.agent_profile === options.agentProfile &&
          item.provider === provider,
      )
    : null;

  if (reuse && reuse.id) {
    return { terminalId: String(reuse.id), provider, reused: true };
  }

  let workingDirectory = options.workingDirectory;
  if (!workingDirectory) {
    try {
      const wd = await requestJson(
        api,
        "GET",
        `/terminals/${currentTerminalId}/working-directory`,
      );
      workingDirectory = wd.working_directory || undefined;
    } catch {
      workingDirectory = undefined;
    }
  }

  const created = await requestJson(api, "POST", `/sessions/${sessionName}/terminals`, {
    agent_profile: options.agentProfile,
    provider,
    working_directory: workingDirectory,
  });

  return { terminalId: String(created.id), provider, reused: false };
}

function registerSendMessageTool(api) {
  api.registerTool({
    name: "cao_send_message",
    label: "CAO Send Message",
    description: "Send a message to another CAO terminal inbox",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        receiver_id: { type: "string", description: "Target CAO terminal id" },
        message: { type: "string", description: "Message to send" },
        sender_id: { type: "string", description: "Sender terminal id" },
      },
      required: ["receiver_id", "message", "sender_id"],
    },
    async execute(_toolCallId, params) {
      const senderId = resolveRequiredTerminalId(params.sender_id, "sender_id");
      const receiverId = resolveRequiredTerminalId(params.receiver_id, "receiver_id");
      const message = String(params.message || "").trim();
      if (!message) {
        throw new Error("Missing required parameter: message");
      }

      const result = await requestJson(
        api,
        "POST",
        `/terminals/${receiverId}/inbox/messages`,
        {
          sender_id: senderId,
          message,
        },
      );

      return asTextResult({ success: true, ...result });
    },
  });
}

function registerAssignTool(api) {
  api.registerTool({
    name: "cao_assign",
    label: "CAO Assign",
    description: "Assign a task to a CAO worker terminal (non-blocking)",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        agent_profile: { type: "string", description: "Target worker agent profile" },
        message: { type: "string", description: "Task message (include callback instruction)" },
        provider: { type: "string", description: "Worker provider override" },
        working_directory: { type: "string", description: "Worker working directory" },
        current_terminal_id: {
          type: "string",
          description: "Supervisor terminal id",
        },
      },
      required: ["agent_profile", "message", "provider", "working_directory", "current_terminal_id"],
    },
    async execute(_toolCallId, params) {
      const currentTerminalId = resolveRequiredTerminalId(
        params.current_terminal_id,
        "current_terminal_id",
      );
      const agentProfile = String(params.agent_profile || "").trim();
      const message = String(params.message || "").trim();
      const provider = String(params.provider || "").trim();
      const workingDirectory = String(params.working_directory || "").trim();
      if (!agentProfile) {
        throw new Error("Missing required parameter: agent_profile");
      }
      if (!message) {
        throw new Error("Missing required parameter: message");
      }
      if (!provider) {
        throw new Error("Missing required parameter: provider");
      }
      if (!workingDirectory) {
        throw new Error("Missing required parameter: working_directory");
      }

      const worker = await findOrCreateWorker(api, {
        currentTerminalId,
        agentProfile,
        provider,
        workingDirectory,
      });

      const inboxResult = await requestJson(
        api,
        "POST",
        `/terminals/${worker.terminalId}/inbox/messages`,
        {
          sender_id: currentTerminalId,
          message,
        },
      );

      return asTextResult({
        success: true,
        terminal_id: worker.terminalId,
        provider: worker.provider,
        reused: worker.reused,
        inbox: inboxResult,
      });
    },
  });
}

function registerHandoffTool(api) {
  api.registerTool({
    name: "cao_handoff",
    label: "CAO Handoff",
    description: "Handoff a task to a CAO worker and wait for completion",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        agent_profile: { type: "string", description: "Target worker agent profile" },
        message: { type: "string", description: "Task message" },
        timeout: {
          type: "number",
          description: "Timeout in seconds",
          minimum: 1,
          maximum: 3600,
          default: 600,
        },
        provider: { type: "string", description: "Worker provider override" },
        working_directory: { type: "string", description: "Worker working directory" },
        current_terminal_id: {
          type: "string",
          description: "Supervisor terminal id",
        },
      },
      required: [
        "agent_profile",
        "message",
        "timeout",
        "provider",
        "working_directory",
        "current_terminal_id",
      ],
    },
    async execute(_toolCallId, params) {
      const timeout = Number(params.timeout || 600);
      const currentTerminalId = resolveRequiredTerminalId(
        params.current_terminal_id,
        "current_terminal_id",
      );
      const agentProfile = String(params.agent_profile || "").trim();
      const message = String(params.message || "").trim();
      const provider = String(params.provider || "").trim();
      const workingDirectory = String(params.working_directory || "").trim();
      if (!agentProfile) {
        throw new Error("Missing required parameter: agent_profile");
      }
      if (!message) {
        throw new Error("Missing required parameter: message");
      }
      if (!provider) {
        throw new Error("Missing required parameter: provider");
      }
      if (!workingDirectory) {
        throw new Error("Missing required parameter: working_directory");
      }

      const worker = await findOrCreateWorker(api, {
        currentTerminalId,
        agentProfile,
        provider,
        workingDirectory,
      });

      if (!worker.reused) {
        const ready = await waitTerminalReady(api, worker.terminalId, 120);
        if (!ready) {
          return asTextResult({
            success: false,
            terminal_id: worker.terminalId,
            message: "worker terminal did not become ready within 120 seconds",
          });
        }
      }

      await requestJson(api, "POST", `/terminals/${worker.terminalId}/input`, {
        message,
      });

      const done = await waitTerminalReady(api, worker.terminalId, timeout);
      if (!done) {
        return asTextResult({
          success: false,
          terminal_id: worker.terminalId,
          provider: worker.provider,
          message: `handoff timeout after ${timeout} seconds`,
        });
      }

      const output = await requestJson(api, "GET", `/terminals/${worker.terminalId}/output`, {
        mode: "last",
      });

      return asTextResult({
        success: true,
        terminal_id: worker.terminalId,
        provider: worker.provider,
        reused: worker.reused,
        output: output.output || "",
      });
    },
  });
}

module.exports = {
  id: "cao-tools",
  name: "CAO Tools",
  description: "Expose CAO handoff/assign/send_message tools to OpenClaw agents",
  register(api) {
    registerSendMessageTool(api);
    registerAssignTool(api);
    registerHandoffTool(api);
    api.logger.info?.("cao-tools plugin registered");
  },
};

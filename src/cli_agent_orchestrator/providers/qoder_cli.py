"""Qoder CLI provider implementation."""

import json
import shlex
from typing import Optional

from cli_agent_orchestrator.providers.simple_tui import SimpleTuiProvider
from cli_agent_orchestrator.utils.agent_profiles import load_agent_profile


class ProviderError(Exception):
    """Exception raised for provider-specific errors."""

    pass


def _build_qoder_mcp_setup_command(agent_profile: Optional[str], terminal_id: str) -> Optional[str]:
    """Build shell command(s) to register MCP servers via `qodercli mcp add`.

    Qoder CLI does not provide a direct per-session `--mcp-config` flag, so we
    register MCP servers through the `mcp` management command before launching
    interactive mode. To ensure configuration is refreshed, existing same-name
    servers are removed first and then re-added with project scope.
    """
    if not agent_profile:
        return None

    try:
        profile = load_agent_profile(agent_profile)
    except Exception as e:
        raise ProviderError(f"Failed to load agent profile '{agent_profile}': {e}")

    if not profile.mcpServers:
        return None

    setup_commands = []

    for server_name, server_config in profile.mcpServers.items():
        if isinstance(server_config, dict):
            cfg = dict(server_config)
        else:
            cfg = server_config.model_dump(exclude_none=True)

        transport = str(cfg.get("type", "stdio"))
        endpoint: Optional[str] = None

        if transport == "stdio":
            command = cfg.get("command")
            if command:
                args = cfg.get("args") or []
                endpoint = shlex.join([str(command), *[str(arg) for arg in args]])
        elif transport in {"sse", "http"}:
            endpoint = cfg.get("url")

        if not endpoint:
            continue

        env = dict(cfg.get("env") or {})
        env.setdefault("CAO_TERMINAL_ID", terminal_id)

        add_parts = [
            "qodercli",
            "mcp",
            "add",
            str(server_name),
            str(endpoint),
            "--transport",
            transport,
            "--scope",
            "project",
        ]
        for env_key, env_val in env.items():
            add_parts.extend(["--env", f"{env_key}={env_val}"])

        remove_parts = [
            "qodercli",
            "mcp",
            "remove",
            str(server_name),
            "--scope",
            "project",
        ]
        setup_commands.append(f"{shlex.join(remove_parts)} >/dev/null 2>&1 || true && {shlex.join(add_parts)}")

    if not setup_commands:
        return None

    return " && ".join(setup_commands)


def _build_qoder_command(agent_profile: Optional[str], terminal_id: str) -> str:
    """Build qodercli command with profile-derived agent configuration."""
    command_parts = ["qodercli", "--yolo"]

    if not agent_profile:
        return shlex.join(command_parts)

    try:
        profile = load_agent_profile(agent_profile)
    except Exception as e:
        raise ProviderError(f"Failed to load agent profile '{agent_profile}': {e}")

    if profile.model:
        command_parts.extend(["--model", profile.model])

    system_prompt = profile.system_prompt if profile.system_prompt is not None else ""
    if system_prompt or profile.tools or profile.mcpServers or profile.model:
        agent_definition = {
            agent_profile: {
                "description": profile.description,
            }
        }
        if system_prompt:
            agent_definition[agent_profile]["prompt"] = system_prompt
        if profile.tools:
            agent_definition[agent_profile]["tools"] = profile.tools
        if profile.model:
            agent_definition[agent_profile]["model"] = profile.model

        command_parts.extend(["--agents", json.dumps(agent_definition)])

    return shlex.join(command_parts)


class QoderCliProvider(SimpleTuiProvider):
    """Provider for Qoder CLI (`qodercli`)."""

    def __init__(
        self,
        terminal_id: str,
        session_name: str,
        window_name: str,
        agent_profile: Optional[str] = None,
    ):
        mcp_setup_command = _build_qoder_mcp_setup_command(agent_profile, terminal_id)
        qoder_command = _build_qoder_command(agent_profile, terminal_id)
        start_command = (
            f"{mcp_setup_command} && {qoder_command}" if mcp_setup_command else qoder_command
        )

        super().__init__(
            terminal_id=terminal_id,
            session_name=session_name,
            window_name=window_name,
            start_command=start_command,
            idle_prompt_pattern=r"[>❯›]\s",
            idle_prompt_pattern_log=r"[>❯›]\s",
            exit_command="/quit",
        )

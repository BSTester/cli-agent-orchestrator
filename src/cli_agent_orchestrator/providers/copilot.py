"""GitHub Copilot CLI provider implementation."""

import json
import shlex
from typing import Optional

from cli_agent_orchestrator.providers.simple_tui import SimpleTuiProvider
from cli_agent_orchestrator.utils.agent_profiles import load_agent_profile


class ProviderError(Exception):
    """Exception raised for provider-specific errors."""

    pass


def _build_copilot_command(agent_profile: Optional[str], terminal_id: str) -> str:
    command_parts = ["copilot", "--allow-all", "--no-ask-user", "--no-alt-screen"]

    if not agent_profile:
        return shlex.join(command_parts)

    try:
        profile = load_agent_profile(agent_profile)
    except Exception as e:
        raise ProviderError(f"Failed to load agent profile '{agent_profile}': {e}")

    command_parts.extend(["--agent", agent_profile])

    if profile.model:
        command_parts.extend(["--model", profile.model])

    if profile.mcpServers:
        mcp_config = {}
        for server_name, server_config in profile.mcpServers.items():
            if isinstance(server_config, dict):
                mcp_config[server_name] = dict(server_config)
            else:
                mcp_config[server_name] = server_config.model_dump(exclude_none=True)

            env = mcp_config[server_name].get("env", {})
            if "CAO_TERMINAL_ID" not in env:
                env["CAO_TERMINAL_ID"] = terminal_id
                mcp_config[server_name]["env"] = env

        command_parts.extend(
            ["--additional-mcp-config", json.dumps({"mcpServers": mcp_config}, ensure_ascii=False)]
        )

    return shlex.join(command_parts)


class CopilotProvider(SimpleTuiProvider):
    """Provider for GitHub Copilot CLI (`copilot`)."""

    _IDLE_PROMPT_PATTERN = r"(?:\b[cC]opilot\s*[>❯›]?\s*$|[>❯›](?:\s|$)|Type\s+@\s+to\s+mention|shift\+tab\s+switch\s+mode)"

    def __init__(
        self,
        terminal_id: str,
        session_name: str,
        window_name: str,
        agent_profile: Optional[str] = None,
    ):
        super().__init__(
            terminal_id=terminal_id,
            session_name=session_name,
            window_name=window_name,
            start_command=_build_copilot_command(agent_profile, terminal_id),
            idle_prompt_pattern=self._IDLE_PROMPT_PATTERN,
            idle_prompt_pattern_log=self._IDLE_PROMPT_PATTERN,
        )

"""CodeBuddy CLI provider implementation."""

import json
import shlex
from typing import Optional

from cli_agent_orchestrator.providers.simple_tui import SimpleTuiProvider
from cli_agent_orchestrator.utils.agent_profiles import load_agent_profile


class ProviderError(Exception):
    """Exception raised for provider-specific errors."""

    pass


def _build_codebuddy_command(agent_profile: Optional[str], terminal_id: str) -> str:
    command_parts = ["codebuddy", "--dangerously-skip-permissions"]

    if not agent_profile:
        return shlex.join(command_parts)

    try:
        profile = load_agent_profile(agent_profile)
    except Exception as e:
        raise ProviderError(f"Failed to load agent profile '{agent_profile}': {e}")

    system_prompt = profile.system_prompt if profile.system_prompt is not None else ""
    if system_prompt or profile.tools or profile.model:
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

        command_parts.extend(["--mcp-config", json.dumps({"mcpServers": mcp_config})])

    return shlex.join(command_parts)


class CodeBuddyProvider(SimpleTuiProvider):
    """Provider for CodeBuddy CLI (`codebuddy`)."""

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
            start_command=_build_codebuddy_command(agent_profile, terminal_id),
            idle_prompt_pattern=r"[>❯›]\s",
            idle_prompt_pattern_log=r"[>❯›]\s",
        )

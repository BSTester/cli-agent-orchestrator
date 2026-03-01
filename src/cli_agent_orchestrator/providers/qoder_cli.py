"""Qoder CLI provider implementation."""

import json
import shlex
from typing import Optional

from cli_agent_orchestrator.providers.simple_tui import SimpleTuiProvider
from cli_agent_orchestrator.utils.agent_profiles import load_agent_profile


class ProviderError(Exception):
    """Exception raised for provider-specific errors."""

    pass


def _build_qoder_command(agent_profile: Optional[str]) -> str:
    """Build qodercli command with profile-derived agent configuration."""
    command_parts = ["qodercli", "--yolo"]

    if not agent_profile:
        return shlex.join(command_parts)

    try:
        profile = load_agent_profile(agent_profile)
    except Exception as e:
        raise ProviderError(f"Failed to load agent profile '{agent_profile}': {e}")

    system_prompt = profile.system_prompt if profile.system_prompt is not None else ""
    if system_prompt:
        agent_definition = {
            agent_profile: {
                "description": profile.description,
                "prompt": system_prompt,
            }
        }
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
        super().__init__(
            terminal_id=terminal_id,
            session_name=session_name,
            window_name=window_name,
            start_command=_build_qoder_command(agent_profile),
            idle_prompt_pattern=r"[>❯›]\s",
            idle_prompt_pattern_log=r"[>❯›]\s",
        )

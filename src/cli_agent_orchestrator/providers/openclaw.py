"""OpenClaw CLI provider implementation."""

from typing import Optional

from cli_agent_orchestrator.providers.simple_tui import SimpleTuiProvider


def _build_openclaw_command(agent_profile: Optional[str]) -> str:
    """Build the OpenClaw launch command.

    OpenClaw currently owns its own agent/runtime prompt composition. CAO's
    integration focuses on launching the interactive CLI/TUI reliably inside
    tmux, without assuming support for per-session system prompt or MCP flag
    injection parity with other providers.
    """
    _ = agent_profile
    return "openclaw"


class OpenClawProvider(SimpleTuiProvider):
    """Provider for OpenClaw CLI (`openclaw`)."""

    _IDLE_PROMPT_PATTERN = (
        r"(?:^[ \t]*[oO]pen[cC]law[ \t]*[>❯›][ \t]*$|"
        r"[>❯›][ \t]+Type your message|"
        r"ctrl\+j[ \t]+for[ \t]+newline|"
        r"shift\+tab\s+switch\s+mode)"
    )

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
            start_command=_build_openclaw_command(agent_profile),
            idle_prompt_pattern=self._IDLE_PROMPT_PATTERN,
            idle_prompt_pattern_log=self._IDLE_PROMPT_PATTERN,
            exit_command="C-c",
        )

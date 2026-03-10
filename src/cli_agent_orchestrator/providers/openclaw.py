"""OpenClaw CLI provider implementation."""

import json
import re
import subprocess
from pathlib import Path
from typing import Any, Optional

from cli_agent_orchestrator.clients.tmux import tmux_client
from cli_agent_orchestrator.constants import OPENCLAW_AGENT_WORKSPACES_DIR
from cli_agent_orchestrator.models.agent_profile import AgentProfile
from cli_agent_orchestrator.models.terminal import TerminalStatus
from cli_agent_orchestrator.providers.simple_tui import SimpleTuiProvider
from cli_agent_orchestrator.utils.agent_profiles import load_agent_profile
from cli_agent_orchestrator.utils.terminal import wait_until_status


class ProviderError(Exception):
    """Exception raised for OpenClaw provider-specific errors."""

    pass


def _build_openclaw_command(agent_profile: Optional[str]) -> str:
    """Build the OpenClaw launch command.

    OpenClaw currently owns its own agent/runtime prompt composition. CAO's
    integration focuses on launching the interactive CLI/TUI reliably inside
    tmux, without assuming support for per-session system prompt or MCP flag
    injection parity with other providers.
    """
    _ = agent_profile
    return "openclaw tui"


def _normalize_openclaw_agent_name(agent_name: str) -> str:
    """Normalize CAO agent names to OpenClaw-compatible identifiers."""
    normalized = re.sub(r"[^a-z0-9]+", "-", agent_name.strip().lower()).strip("-")
    if not normalized:
        raise ProviderError(f"Invalid OpenClaw agent name derived from '{agent_name}'")
    return normalized


def _build_openclaw_soul(profile: AgentProfile) -> str:
    """Build SOUL.md content for an OpenClaw agent workspace."""
    soul = (profile.system_prompt or profile.prompt or profile.description).strip()
    if not soul:
        raise ProviderError(f"Agent profile '{profile.name}' does not contain any prompt content")
    return soul


def _extract_openclaw_agent_ids(payload: Any) -> set[str]:
    """Recursively extract agent ids/names from agents list payload."""
    if isinstance(payload, dict):
        ids: set[str] = set()
        for key, value in payload.items():
            if key in {"id", "name"} and isinstance(value, str):
                ids.add(value)
            ids.update(_extract_openclaw_agent_ids(value))
        return ids
    if isinstance(payload, list):
        list_ids: set[str] = set()
        for item in payload:
            list_ids.update(_extract_openclaw_agent_ids(item))
        return list_ids
    return set()


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
        self._agent_profile = agent_profile
        self._openclaw_agent_name: Optional[str] = None
        super().__init__(
            terminal_id=terminal_id,
            session_name=session_name,
            window_name=window_name,
            start_command=_build_openclaw_command(agent_profile),
            idle_prompt_pattern=self._IDLE_PROMPT_PATTERN,
            idle_prompt_pattern_log=self._IDLE_PROMPT_PATTERN,
            exit_command="C-c",
        )

    def _run_openclaw_command(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        """Run an OpenClaw CLI command and return the completed process."""
        try:
            return subprocess.run(args, capture_output=True, text=True, check=True)
        except subprocess.CalledProcessError as exc:
            details = (exc.stderr or exc.stdout or str(exc)).strip()
            raise ProviderError(f"Failed to run {' '.join(args)}: {details}") from exc

    def _load_openclaw_profile(self) -> AgentProfile:
        """Load the configured CAO agent profile for OpenClaw bootstrap."""
        if self._agent_profile is None:
            raise ProviderError("OpenClaw agent bootstrap requires agent_profile")

        try:
            profile = load_agent_profile(self._agent_profile)
        except Exception as exc:
            raise ProviderError(
                f"Failed to load agent profile '{self._agent_profile}': {exc}"
            ) from exc

        self._openclaw_agent_name = _normalize_openclaw_agent_name(profile.name)
        return profile

    def _openclaw_agent_exists(self, agent_name: str) -> bool:
        """Return whether an OpenClaw agent id is already registered."""
        result = self._run_openclaw_command(["openclaw", "agents", "list", "--json"])

        try:
            payload = json.loads(result.stdout or "{}")
        except json.JSONDecodeError:
            return agent_name in result.stdout

        return agent_name in _extract_openclaw_agent_ids(payload)

    def _ensure_openclaw_agent_registered(self) -> None:
        """Register the CAO agent profile with OpenClaw if needed."""
        if self._agent_profile is None:
            return

        profile = self._load_openclaw_profile()
        if self._openclaw_agent_name is None:
            raise ProviderError("OpenClaw agent name was not initialized")

        if self._openclaw_agent_exists(self._openclaw_agent_name):
            return

        workspace_dir = OPENCLAW_AGENT_WORKSPACES_DIR / self._openclaw_agent_name
        workspace_dir.mkdir(parents=True, exist_ok=True)
        (workspace_dir / "SOUL.md").write_text(_build_openclaw_soul(profile))

        self._run_openclaw_command(
            [
                "openclaw",
                "agents",
                "add",
                self._openclaw_agent_name,
                "--workspace",
                str(workspace_dir),
                "--non-interactive",
            ]
        )

    def _reset_bootstrap_state(self) -> None:
        """Reset transient input tracking after internal bootstrap commands."""
        self._input_received = False
        self._input_received_at = None
        self._saw_processing_after_input = False

    def _switch_to_openclaw_agent(self) -> None:
        """Switch the TUI session to the desired OpenClaw agent."""
        if self._openclaw_agent_name is None:
            return

        self.mark_input_received()
        tmux_client.send_keys(
            self.session_name,
            self.window_name,
            f"/agent {self._openclaw_agent_name}",
        )

        if not wait_until_status(
            self,
            {TerminalStatus.IDLE, TerminalStatus.COMPLETED},
            timeout=20.0,
            polling_interval=1.0,
        ):
            raise TimeoutError("OpenClaw agent switch timed out after 20 seconds")

        self._reset_bootstrap_state()

    def initialize(self) -> bool:
        """Initialize OpenClaw and switch to the configured agent profile if needed."""
        self._ensure_openclaw_agent_registered()
        super().initialize()
        self._switch_to_openclaw_agent()
        return True

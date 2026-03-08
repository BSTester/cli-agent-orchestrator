"""Plain shell provider for ephemeral control-panel terminals."""

from typing import Optional

from cli_agent_orchestrator.clients.tmux import tmux_client
from cli_agent_orchestrator.models.terminal import TerminalStatus
from cli_agent_orchestrator.providers.base import BaseProvider


class ShellProvider(BaseProvider):
    """Provider that leaves the tmux pane as a normal Linux shell."""

    @property
    def paste_enter_count(self) -> int:
        return 1

    def initialize(self) -> bool:
        self._update_status(TerminalStatus.IDLE)
        return True

    def get_status(self, tail_lines: Optional[int] = None) -> TerminalStatus:
        self._update_status(TerminalStatus.IDLE)
        return self._status

    def get_idle_pattern_for_log(self) -> str:
        return ""

    def extract_last_message_from_script(self, script_output: str) -> str:
        return script_output

    def exit_cli(self) -> str:
        return "C-d"

    def cleanup(self) -> None:
        try:
            tmux_client.kill_window(self.session_name, self.window_name)
        except Exception:
            pass
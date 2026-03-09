"""Unit tests for OpenClaw provider prompt detection."""

from unittest.mock import patch

from cli_agent_orchestrator.models.terminal import TerminalStatus
from cli_agent_orchestrator.providers.openclaw import OpenClawProvider


@patch("cli_agent_orchestrator.providers.simple_tui.tmux_client")
def test_openclaw_prompt_detected_as_idle(mock_tmux) -> None:
    mock_tmux.get_history.return_value = "OpenClaw ready\nopenclaw >"

    provider = OpenClawProvider("t1", "s1", "w1")

    assert provider.get_status() == TerminalStatus.IDLE


@patch("cli_agent_orchestrator.providers.simple_tui.tmux_client")
def test_openclaw_hint_detected_as_idle(mock_tmux) -> None:
    mock_tmux.get_history.return_value = (
        "OpenClaw v0.1\n"
        "❯  Type your message\n"
        "shift+tab switch mode\n"
    )

    provider = OpenClawProvider("t2", "s2", "w2")

    assert provider.get_status() == TerminalStatus.IDLE
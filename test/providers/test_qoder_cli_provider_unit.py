"""Unit tests for Qoder CLI provider prompt detection."""

from unittest.mock import patch

from cli_agent_orchestrator.models.terminal import TerminalStatus
from cli_agent_orchestrator.providers.qoder_cli import QoderCliProvider


@patch("cli_agent_orchestrator.providers.simple_tui.tmux_client")
def test_qoder_prompt_detected_as_idle(mock_tmux) -> None:
    """Ensure qoder prompt without trailing space is treated as idle."""
    mock_tmux.get_history.return_value = "Qoder ready\nqoder>"

    provider = QoderCliProvider("t1", "s1", "w1")

    assert provider.get_status() == TerminalStatus.IDLE


@patch("cli_agent_orchestrator.providers.simple_tui.tmux_client")
def test_qoder_prompt_with_input_hint(mock_tmux) -> None:
    """Ensure '>' input hint lines are treated as idle."""
    mock_tmux.get_history.return_value = (
        "Tips for getting started:\n"
        "1. Ask questions\n"
        "\n"
        "> Type your message...\n"
        "? for shortcuts, ctrl+j for newline\n"
    )

    provider = QoderCliProvider("t2", "s2", "w2")

    assert provider.get_status() == TerminalStatus.IDLE

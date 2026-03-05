"""Unit tests for Copilot provider prompt detection."""

from unittest.mock import patch

from cli_agent_orchestrator.models.terminal import TerminalStatus
from cli_agent_orchestrator.providers.copilot import CopilotProvider


@patch("cli_agent_orchestrator.providers.simple_tui.tmux_client")
def test_copilot_prompt_detected_as_idle(mock_tmux) -> None:
    """Ensure copilot> prompt is treated as idle to avoid init timeouts."""
    mock_tmux.get_history.return_value = "Welcome to Copilot\ncopilot>"

    provider = CopilotProvider("t1", "s1", "w1")

    assert provider.get_status() == TerminalStatus.IDLE


@patch("cli_agent_orchestrator.providers.simple_tui.tmux_client")
def test_copilot_prompt_with_arrow_symbol(mock_tmux) -> None:
    """Copilot prompt using ❯ should also be treated as idle."""
    mock_tmux.get_history.return_value = "Welcome to Copilot\ncopilot ❯"

    provider = CopilotProvider("t2", "s2", "w2")

    assert provider.get_status() == TerminalStatus.IDLE


@patch("cli_agent_orchestrator.providers.simple_tui.tmux_client")
def test_copilot_prompt_with_input_hint(mock_tmux) -> None:
    """Copilot hint line starting with ❯ should count as idle prompt."""
    mock_tmux.get_history.return_value = (
        "GitHub Copilot v0.0.421\n"
        "Tip: /plugin Manage plugins\n"
        "\n"
        "❯  Type @ to mention files, # for issues/PRs, / for commands\n"
    )

    provider = CopilotProvider("t3", "s3", "w3")

    assert provider.get_status() == TerminalStatus.IDLE

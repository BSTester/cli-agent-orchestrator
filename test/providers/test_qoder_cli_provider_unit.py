"""Unit tests for Qoder CLI provider prompt detection."""

from unittest.mock import MagicMock
from unittest.mock import patch

from cli_agent_orchestrator.models.terminal import TerminalStatus
from cli_agent_orchestrator.providers.qoder_cli import _build_qoder_mcp_setup_command
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


@patch("cli_agent_orchestrator.providers.simple_tui.tmux_client")
def test_qoder_non_fatal_mcp_add_error_does_not_block_idle(mock_tmux) -> None:
    """Ignore non-fatal MCP add conflict message when prompt is already idle."""
    mock_tmux.get_history.return_value = (
        "Error adding MCP server: %v\n"
        "MCP server cao-mcp-server already exists in project /home/penn/workspace\n"
        "\n"
        "╭─────────────────────────────────────────────────────────────────────────────╮\n"
        "│ > Type your message...                                                      │\n"
        "╰─────────────────────────────────────────────────────────────────────────────╯\n"
    )

    provider = QoderCliProvider("t3", "s3", "w3")

    assert provider.get_status() == TerminalStatus.IDLE


@patch("cli_agent_orchestrator.providers.simple_tui.tmux_client")
def test_qoder_real_error_still_reports_error(mock_tmux) -> None:
    """Real startup errors should still be reported as ERROR."""
    mock_tmux.get_history.return_value = "Error: command not found: qodercli\n"

    provider = QoderCliProvider("t4", "s4", "w4")

    assert provider.get_status() == TerminalStatus.ERROR


@patch("cli_agent_orchestrator.providers.qoder_cli.load_agent_profile")
def test_qoder_mcp_remove_uses_no_scope(mock_load_profile) -> None:
    """qodercli mcp remove should run without --scope to avoid silent remove failures."""
    profile = MagicMock()
    profile.mcpServers = {
        "cao-mcp-server": {
            "type": "stdio",
            "command": "cao-mcp-server",
        }
    }
    mock_load_profile.return_value = profile

    command = _build_qoder_mcp_setup_command("developer", "t-123")

    assert command is not None
    assert "qodercli mcp remove cao-mcp-server" in command
    assert "qodercli mcp remove cao-mcp-server --scope project" not in command


@patch("cli_agent_orchestrator.providers.simple_tui.tmux_client")
def test_qoder_idle_not_overridden_by_command_echo_working_text(mock_tmux) -> None:
    """Words like 'working' in echoed prompt text should not force PROCESSING."""
    mock_tmux.get_history.return_value = (
        "...translate requirements into working software implementations...\n"
        "\n"
        "│ > Type your message...                                                      │\n"
    )

    provider = QoderCliProvider("t5", "s5", "w5")

    assert provider.get_status() == TerminalStatus.IDLE

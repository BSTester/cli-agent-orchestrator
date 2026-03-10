"""Unit tests for Copilot provider prompt detection."""

import json
import shlex
from unittest.mock import patch

from cli_agent_orchestrator.models.terminal import TerminalStatus
from cli_agent_orchestrator.providers.copilot import CopilotProvider
from cli_agent_orchestrator.providers.copilot import _build_copilot_command


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


@patch("cli_agent_orchestrator.providers.simple_tui.tmux_client")
def test_copilot_prompt_with_trailing_blank_lines(mock_tmux) -> None:
    """Idle prompt followed by many blank lines (tmux pane padding) must still be detected."""
    mock_tmux.get_history.return_value = (
        "GitHub Copilot v0.0.421\n"
        "● Selected custom agent: cto\n"
        "● Environment loaded: 3 MCP servers\n"
        " ~/workspace\n"
        "───────────────────────\n"
        "❯  Type @ to mention files, # for issues/PRs, / for commands\n"
        "───────────────────────\n"
        " shift+tab switch mode \n"
        + "\n" * 30  # simulate unused pane rows
    )

    provider = CopilotProvider("t4", "s4", "w4")

    assert provider.get_status() == TerminalStatus.IDLE


@patch("cli_agent_orchestrator.providers.simple_tui.tmux_client")
def test_copilot_type_hint_detected_as_idle(mock_tmux) -> None:
    """'Type @ to mention' text should be detected as idle even without ❯ char."""
    mock_tmux.get_history.return_value = (
        "GitHub Copilot v0.0.421\n"
        "───────────────────────\n"
        "  Type @ to mention files, # for issues/PRs, / for commands\n"
    )

    provider = CopilotProvider("t5", "s5", "w5")

    assert provider.get_status() == TerminalStatus.IDLE


@patch("cli_agent_orchestrator.providers.simple_tui.tmux_client")
def test_copilot_shift_tab_hint_detected_as_idle(mock_tmux) -> None:
    """'shift+tab switch mode' hint should be detected as idle."""
    mock_tmux.get_history.return_value = (
        "GitHub Copilot v0.0.421\n"
        " shift+tab switch mode \n"
    )

    provider = CopilotProvider("t6", "s6", "w6")

    assert provider.get_status() == TerminalStatus.IDLE


@patch("cli_agent_orchestrator.providers.simple_tui.tmux_client")
def test_copilot_ansi_csi_sequences_stripped(mock_tmux) -> None:
    """Non-SGR CSI sequences (e.g. erase-line) should be stripped before matching."""
    mock_tmux.get_history.return_value = (
        "\x1b[2J\x1b[HGitHub Copilot v0.0.421\n"
        "\x1b[K❯  Type @ to mention files\n"
    )

    provider = CopilotProvider("t7", "s7", "w7")

    assert provider.get_status() == TerminalStatus.IDLE


@patch("cli_agent_orchestrator.providers.copilot.load_agent_profile")
def test_build_copilot_command_adds_empty_args_for_command_only_mcp_server(mock_load_profile) -> None:
    """Command-based MCP server config should include args to satisfy Copilot schema."""
    profile = type(
        "Profile",
        (),
        {
            "model": None,
            "mcpServers": {
                "cao-mcp-server": {
                    "command": "cao-mcp-server",
                }
            },
        },
    )()
    mock_load_profile.return_value = profile

    command = _build_copilot_command("developer", "t-123")
    parts = shlex.split(command)
    config_json = parts[parts.index("--additional-mcp-config") + 1]
    config = json.loads(config_json)

    server_cfg = config["mcpServers"]["cao-mcp-server"]
    assert server_cfg["command"] == "cao-mcp-server"
    assert server_cfg["args"] == []
    assert server_cfg["env"]["CAO_TERMINAL_ID"] == "t-123"

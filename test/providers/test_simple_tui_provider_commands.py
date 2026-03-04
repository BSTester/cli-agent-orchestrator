"""Unit tests for SimpleTui-based provider startup commands."""

from unittest.mock import MagicMock, patch

from cli_agent_orchestrator.providers.codebuddy import CodeBuddyProvider
from cli_agent_orchestrator.providers.copilot import CopilotProvider
from cli_agent_orchestrator.providers.qoder_cli import QoderCliProvider


def test_qoder_cli_start_command_uses_yolo() -> None:
    provider = QoderCliProvider("t1", "s1", "w1")
    assert provider._start_command == "qodercli --yolo"


def test_qoder_cli_exit_command_is_quit() -> None:
    provider = QoderCliProvider("t1", "s1", "w1")
    assert provider.exit_cli() == "/quit"


@patch("cli_agent_orchestrator.providers.qoder_cli.load_agent_profile")
def test_qoder_cli_start_command_with_agent_profile(mock_load_profile) -> None:
    mock_profile = MagicMock()
    mock_profile.description = "Code supervisor"
    mock_profile.system_prompt = "You are a code supervisor"
    mock_profile.tools = ["Read", "Edit"]
    mock_profile.model = "gmodel"
    mock_profile.mcpServers = {
        "cao-mcp-server": {
            "command": "uvx",
            "args": ["cao-mcp-server"],
        }
    }
    mock_load_profile.return_value = mock_profile

    provider = QoderCliProvider("term123", "s1", "w1", "code_supervisor")

    assert "qodercli mcp remove cao-mcp-server --scope project" in provider._start_command
    assert "qodercli mcp add cao-mcp-server" in provider._start_command
    assert "--transport stdio" in provider._start_command
    assert "--scope project" in provider._start_command
    assert "--env CAO_TERMINAL_ID=term123" in provider._start_command
    assert " && qodercli --yolo" in provider._start_command
    assert "--agents" in provider._start_command
    assert "--model gmodel" in provider._start_command
    assert "code_supervisor" in provider._start_command
    assert "You are a code supervisor" in provider._start_command
    assert "Read" in provider._start_command
    assert "Edit" in provider._start_command
    assert "gmodel" in provider._start_command
    # MCP is configured via `qodercli mcp add`, not embedded in --agents JSON.
    assert '"mcpServers"' not in provider._start_command


def test_codebuddy_start_command_skips_permissions() -> None:
    provider = CodeBuddyProvider("t1", "s1", "w1")
    assert provider._start_command == "codebuddy --dangerously-skip-permissions"
    assert provider._auto_accept_input == "3"


@patch("cli_agent_orchestrator.providers.codebuddy.load_agent_profile")
def test_codebuddy_start_command_includes_profile_prompt_and_mcp(mock_load_profile) -> None:
    mock_profile = MagicMock()
    mock_profile.description = "Code supervisor"
    mock_profile.system_prompt = "Follow CAO orchestration"
    mock_profile.tools = ["Read", "Edit"]
    mock_profile.model = "glm-4.7"
    mock_profile.mcpServers = {
        "cao-mcp-server": {
            "command": "uvx",
            "args": ["cao-mcp-server"],
        }
    }
    mock_load_profile.return_value = mock_profile

    provider = CodeBuddyProvider("term123", "s1", "w1", "code_supervisor")

    assert "--agents" in provider._start_command
    assert "--agent code_supervisor" not in provider._start_command
    assert "Follow CAO orchestration" in provider._start_command
    assert "code_supervisor" in provider._start_command
    assert "--model glm-4.7" in provider._start_command
    assert "--append-system-prompt" not in provider._start_command
    assert "--mcp-config" in provider._start_command
    assert "--strict-mcp-config" not in provider._start_command
    assert "cao-mcp-server" in provider._start_command
    assert "CAO_TERMINAL_ID" in provider._start_command
    assert "term123" in provider._start_command


def test_copilot_start_command_allows_all_without_ask_user() -> None:
    provider = CopilotProvider("t1", "s1", "w1")
    assert provider._start_command == "copilot --allow-all --no-ask-user --no-alt-screen"


@patch("cli_agent_orchestrator.providers.copilot.load_agent_profile")
def test_copilot_start_command_includes_profile_and_mcp(mock_load_profile) -> None:
    mock_profile = MagicMock()
    mock_profile.model = "gpt-5.3-codex"
    mock_profile.mcpServers = {
        "cao-mcp-server": {
            "command": "uvx",
            "args": ["cao-mcp-server"],
        }
    }
    mock_load_profile.return_value = mock_profile

    provider = CopilotProvider("term123", "s1", "w1", "code_supervisor")

    assert "--agent code_supervisor" in provider._start_command
    assert "--model gpt-5.3-codex" in provider._start_command
    assert "--additional-mcp-config" in provider._start_command
    assert "cao-mcp-server" in provider._start_command
    assert "CAO_TERMINAL_ID" in provider._start_command
    assert "term123" in provider._start_command

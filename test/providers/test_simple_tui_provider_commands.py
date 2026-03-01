"""Unit tests for SimpleTui-based provider startup commands."""

from unittest.mock import MagicMock, patch

from cli_agent_orchestrator.providers.codebuddy import CodeBuddyProvider
from cli_agent_orchestrator.providers.copilot import CopilotProvider
from cli_agent_orchestrator.providers.qoder_cli import QoderCliProvider


def test_qoder_cli_start_command_uses_yolo() -> None:
    provider = QoderCliProvider("t1", "s1", "w1")
    assert provider._start_command == "qodercli --yolo"


@patch("cli_agent_orchestrator.providers.qoder_cli.load_agent_profile")
def test_qoder_cli_start_command_with_agent_profile(mock_load_profile) -> None:
    mock_profile = MagicMock()
    mock_profile.description = "Code supervisor"
    mock_profile.system_prompt = "You are a code supervisor"
    mock_profile.tools = ["Read", "Edit"]
    mock_profile.model = "gmodel"
    mock_load_profile.return_value = mock_profile

    provider = QoderCliProvider("t1", "s1", "w1", "code_supervisor")

    assert provider._start_command.startswith("qodercli --yolo --agents")
    assert "code_supervisor" in provider._start_command
    assert "You are a code supervisor" in provider._start_command
    assert "Read" in provider._start_command
    assert "Edit" in provider._start_command
    assert "gmodel" in provider._start_command


def test_codebuddy_start_command_skips_permissions() -> None:
    provider = CodeBuddyProvider("t1", "s1", "w1")
    assert provider._start_command == "codebuddy --dangerously-skip-permissions"


@patch("cli_agent_orchestrator.providers.codebuddy.load_agent_profile")
def test_codebuddy_start_command_includes_profile_prompt_and_mcp(mock_load_profile) -> None:
    mock_profile = MagicMock()
    mock_profile.system_prompt = "Follow CAO orchestration"
    mock_profile.mcpServers = {
        "cao-mcp-server": {
            "command": "uvx",
            "args": ["cao-mcp-server"],
        }
    }
    mock_load_profile.return_value = mock_profile

    provider = CodeBuddyProvider("term123", "s1", "w1", "code_supervisor")

    assert "--append-system-prompt" in provider._start_command
    assert "Follow CAO orchestration" in provider._start_command
    assert "--mcp-config" in provider._start_command
    assert "cao-mcp-server" in provider._start_command
    assert "CAO_TERMINAL_ID" in provider._start_command
    assert "term123" in provider._start_command


def test_copilot_start_command_allows_all_without_ask_user() -> None:
    provider = CopilotProvider("t1", "s1", "w1")
    assert provider._start_command == "copilot --allow-all --no-ask-user --no-alt-screen"


@patch("cli_agent_orchestrator.providers.copilot.load_agent_profile")
def test_copilot_start_command_includes_profile_and_mcp(mock_load_profile) -> None:
    mock_profile = MagicMock()
    mock_profile.mcpServers = {
        "cao-mcp-server": {
            "command": "uvx",
            "args": ["cao-mcp-server"],
        }
    }
    mock_load_profile.return_value = mock_profile

    provider = CopilotProvider("term123", "s1", "w1", "code_supervisor")

    assert "--agent code_supervisor" in provider._start_command
    assert "--additional-mcp-config" in provider._start_command
    assert "cao-mcp-server" in provider._start_command
    assert "CAO_TERMINAL_ID" in provider._start_command
    assert "term123" in provider._start_command

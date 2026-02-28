"""Unit tests for SimpleTui-based provider startup commands."""

from cli_agent_orchestrator.providers.codebuddy import CodeBuddyProvider
from cli_agent_orchestrator.providers.copilot import CopilotProvider
from cli_agent_orchestrator.providers.qoder_cli import QoderCliProvider


def test_qoder_cli_start_command_uses_yolo() -> None:
    provider = QoderCliProvider("t1", "s1", "w1")
    assert provider._start_command == "qodercli --yolo"


def test_codebuddy_start_command_skips_permissions() -> None:
    provider = CodeBuddyProvider("t1", "s1", "w1")
    assert provider._start_command == "codebuddy --dangerously-skip-permissions"


def test_copilot_start_command_allows_all_without_ask_user() -> None:
    provider = CopilotProvider("t1", "s1", "w1")
    assert provider._start_command == "copilot --allow-all --no-ask-user --no-alt-screen"

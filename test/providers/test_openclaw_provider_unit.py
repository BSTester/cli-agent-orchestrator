"""Unit tests for OpenClaw provider behavior."""

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from cli_agent_orchestrator.models.terminal import TerminalStatus
from cli_agent_orchestrator.providers.openclaw import (
    OpenClawProvider,
    ProviderError,
    _OPENCLAW_TERMINAL_ID_NOTICE_TEMPLATE,
    _build_openclaw_soul,
)


@patch("cli_agent_orchestrator.providers.simple_tui.tmux_client")
def test_openclaw_prompt_detected_as_idle(mock_tmux) -> None:
    mock_tmux.get_history.return_value = "OpenClaw ready\nopenclaw >"

    provider = OpenClawProvider("t1", "s1", "w1")

    assert provider.get_status() == TerminalStatus.IDLE


@patch("cli_agent_orchestrator.providers.simple_tui.tmux_client")
def test_openclaw_hint_detected_as_idle(mock_tmux) -> None:
    mock_tmux.get_history.return_value = (
        "OpenClaw v0.1\n" "❯  Type your message\n" "shift+tab switch mode\n"
    )

    provider = OpenClawProvider("t2", "s2", "w2")

    assert provider.get_status() == TerminalStatus.IDLE


@patch("cli_agent_orchestrator.providers.simple_tui.tmux_client")
def test_openclaw_status_bar_idle_detected_as_idle(mock_tmux) -> None:
    mock_tmux.get_history.return_value = (
        "/agent ceo\n\n"
        "CEO 模式已经是激活状态了！🎯\n\n"
        "gateway connected | idle\n"
        "agent main | session main (openclaw-tui) | moonshot/kimi-k2.5 | tokens ?/256k\n"
    )

    provider = OpenClawProvider("t3", "s3", "w3")

    assert provider.get_status() == TerminalStatus.IDLE


@patch("cli_agent_orchestrator.providers.simple_tui.tmux_client")
def test_openclaw_status_bar_idle_without_gateway_detected_as_idle(mock_tmux) -> None:
    mock_tmux.get_history.return_value = (
        "你想怎么用 MCP？ 告诉我你的场景，我可以推荐最佳方案：\n"
        "- 是想在 Claude Desktop 中使用 CAO 工具？\n"
        "- 还是想让我帮你执行某些 CAO 功能？\n"
        "- 或者是其他需求？\n"
        "connected | idle\n"
        "agent cto (cto) | session main (openclaw-tui) | moonshot/kimi-k2.5 | tokens ?/256k\n"
    )

    provider = OpenClawProvider("t3b", "s3", "w3")

    assert provider.get_status() == TerminalStatus.IDLE


@patch("cli_agent_orchestrator.providers.simple_tui.tmux_client")
def test_openclaw_running_status_bar_detected_as_processing(mock_tmux) -> None:
    mock_tmux.get_history.return_value = (
        "❯  Type your message\n"
        "shift+tab switch mode\n"
        "\n"
        "shei\n"
        "\n"
        "⠼ running • 2s | connected\n"
        "agent ceo (ceo) | session main (openclaw-tui) | moonshot/kimi-k2.5 | tokens ?/256k\n"
    )

    provider = OpenClawProvider("t4", "s4", "w4")
    provider._input_received = True
    provider._input_received_at = 1_234_567_890.0

    assert provider.get_status() == TerminalStatus.PROCESSING


class TestOpenClawProviderInitialization:
    def test_build_openclaw_soul_falls_back_through_profile_fields(self) -> None:
        profile = MagicMock()
        profile.name = "ceo"
        profile.system_prompt = None
        profile.prompt = None
        profile.description = "Lead the company"

        assert _build_openclaw_soul(profile) == "Lead the company"

    @patch("cli_agent_orchestrator.providers.openclaw.wait_until_status")
    @patch("cli_agent_orchestrator.providers.openclaw.load_agent_profile")
    @patch("cli_agent_orchestrator.providers.openclaw.subprocess.run")
    @patch("cli_agent_orchestrator.providers.openclaw.tmux_client")
    @patch("cli_agent_orchestrator.providers.simple_tui.tmux_client")
    @patch("cli_agent_orchestrator.providers.simple_tui.wait_until_status")
    @patch("cli_agent_orchestrator.providers.simple_tui.wait_for_shell")
    def test_initialize_registers_and_switches_agent(
        self,
        mock_wait_shell,
        mock_simple_wait_status,
        mock_simple_tmux,
        mock_tmux,
        mock_subprocess,
        mock_load_profile,
        mock_wait_switch,
        tmp_path: Path,
    ) -> None:
        mock_wait_shell.return_value = True
        mock_simple_wait_status.return_value = True
        mock_wait_switch.return_value = True
        mock_simple_tmux.get_history.return_value = "❯  Type your message\nshift+tab switch mode\n"
        mock_profile = MagicMock()
        mock_profile.name = "CEO"
        mock_profile.system_prompt = "Lead the company."
        mock_profile.prompt = None
        mock_profile.description = "Chief executive officer"
        mock_load_profile.return_value = mock_profile
        mock_subprocess.side_effect = [
            MagicMock(stdout='{"agents":{"list":[]}}', stderr=""),
            MagicMock(stdout="added", stderr=""),
        ]

        with patch(
            "cli_agent_orchestrator.providers.openclaw.OPENCLAW_AGENT_WORKSPACES_DIR", tmp_path
        ):
            provider = OpenClawProvider("t1", "s1", "w1", "ceo")
            result = provider.initialize()

        assert result is True
        assert (tmp_path / "ceo" / "SOUL.md").read_text() == "Lead the company."
        assert mock_subprocess.call_args_list == [
            call(
                ["openclaw", "agents", "list", "--json"],
                capture_output=True,
                text=True,
                check=True,
            ),
            call(
                [
                    "openclaw",
                    "agents",
                    "add",
                    "ceo",
                    "--workspace",
                    str(tmp_path / "ceo"),
                    "--non-interactive",
                ],
                capture_output=True,
                text=True,
                check=True,
            ),
        ]
        assert mock_simple_tmux.send_keys.call_args_list == [
            call("s1", "w1", "CAO_TERMINAL_ID=t1 openclaw tui"),
        ]
        assert mock_tmux.send_keys.call_args_list == [
            call("s1", "w1", "/agent ceo"),
            call(
                "s1",
                "w1",
                _OPENCLAW_TERMINAL_ID_NOTICE_TEMPLATE.format(terminal_id="t1"),
                enter_count=provider.paste_enter_count,
            ),
        ]
        assert mock_wait_switch.call_args_list[0].args[1] == {
            TerminalStatus.IDLE,
            TerminalStatus.COMPLETED,
        }
        assert mock_wait_switch.call_args_list[1].args[1] == {
            TerminalStatus.IDLE,
            TerminalStatus.COMPLETED,
        }
        assert provider._input_received is False

    @patch("cli_agent_orchestrator.providers.openclaw.wait_until_status")
    @patch("cli_agent_orchestrator.providers.openclaw.load_agent_profile")
    @patch("cli_agent_orchestrator.providers.openclaw.subprocess.run")
    @patch("cli_agent_orchestrator.providers.openclaw.tmux_client")
    @patch("cli_agent_orchestrator.providers.simple_tui.tmux_client")
    @patch("cli_agent_orchestrator.providers.simple_tui.wait_until_status")
    @patch("cli_agent_orchestrator.providers.simple_tui.wait_for_shell")
    def test_initialize_skips_registration_for_existing_agent(
        self,
        mock_wait_shell,
        mock_simple_wait_status,
        mock_simple_tmux,
        mock_tmux,
        mock_subprocess,
        mock_load_profile,
        mock_wait_switch,
    ) -> None:
        mock_wait_shell.return_value = True
        mock_simple_wait_status.return_value = True
        mock_wait_switch.return_value = True
        mock_simple_tmux.get_history.return_value = "❯  Type your message\nshift+tab switch mode\n"
        mock_profile = MagicMock()
        mock_profile.name = "Code Supervisor"
        mock_profile.system_prompt = "Guide the team."
        mock_profile.prompt = None
        mock_profile.description = "Supervisor"
        mock_load_profile.return_value = mock_profile
        mock_subprocess.return_value = MagicMock(
            stdout='{"agents":{"list":[{"id":"code-supervisor"}]}}',
            stderr="",
        )

        provider = OpenClawProvider("t1", "s1", "w1", "code_supervisor")
        provider.initialize()

        mock_subprocess.assert_called_once_with(
            ["openclaw", "agents", "list", "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        # OpenClaw agent IDs use normalized kebab-case names.
        mock_simple_tmux.send_keys.assert_called_once_with(
            "s1", "w1", "CAO_TERMINAL_ID=t1 openclaw tui"
        )
        assert mock_tmux.send_keys.call_args_list == [
            call("s1", "w1", "/agent code-supervisor"),
            call(
                "s1",
                "w1",
                _OPENCLAW_TERMINAL_ID_NOTICE_TEMPLATE.format(terminal_id="t1"),
                enter_count=provider.paste_enter_count,
            ),
        ]

    @patch("cli_agent_orchestrator.providers.openclaw.subprocess.run")
    @patch("cli_agent_orchestrator.providers.openclaw.load_agent_profile")
    def test_initialize_raises_provider_error_on_invalid_agent_profile(
        self, mock_load_profile, mock_subprocess
    ) -> None:
        mock_subprocess.return_value = MagicMock(stdout="", stderr="")
        mock_load_profile.side_effect = RuntimeError("missing profile")
        provider = OpenClawProvider("t1", "s1", "w1", "missing")

        with pytest.raises(ProviderError, match="Failed to load agent profile"):
            provider._ensure_openclaw_agent_registered()

    @patch("cli_agent_orchestrator.providers.openclaw.tmux_client")
    @patch("cli_agent_orchestrator.providers.openclaw.wait_until_status")
    def test_switch_to_openclaw_agent_times_out(self, mock_wait_status, mock_tmux) -> None:
        mock_wait_status.return_value = False
        provider = OpenClawProvider("t1", "s1", "w1", "ceo")
        provider._openclaw_agent_name = "ceo"

        with pytest.raises(TimeoutError, match="OpenClaw agent switch timed out"):
            provider._switch_to_openclaw_agent()

        mock_tmux.send_keys.assert_called_once_with("s1", "w1", "/agent ceo")

    @patch("cli_agent_orchestrator.providers.openclaw.tmux_client")
    @patch("cli_agent_orchestrator.providers.openclaw.wait_until_status")
    def test_send_terminal_id_notice_times_out(self, mock_wait_status, mock_tmux) -> None:
        mock_wait_status.return_value = False
        provider = OpenClawProvider("t1", "s1", "w1", "ceo")

        with pytest.raises(TimeoutError, match="terminal-id bootstrap notice timed out"):
            provider._send_terminal_id_notice()

        mock_tmux.send_keys.assert_called_once_with(
            "s1",
            "w1",
            _OPENCLAW_TERMINAL_ID_NOTICE_TEMPLATE.format(terminal_id="t1"),
            enter_count=provider.paste_enter_count,
        )

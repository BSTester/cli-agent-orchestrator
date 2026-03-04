"""Unit tests for SimpleTui startup auto-accept behavior."""

import time
from unittest.mock import MagicMock, patch

from cli_agent_orchestrator.models.terminal import TerminalStatus
from cli_agent_orchestrator.providers.simple_tui import SimpleTuiProvider


@patch("cli_agent_orchestrator.providers.simple_tui.time.sleep", return_value=None)
@patch("cli_agent_orchestrator.providers.simple_tui.tmux_client")
def test_auto_accept_runs_before_idle_detection(mock_tmux, _mock_sleep):
    """When a trust menu contains '> 3', provider should still auto-accept first."""
    provider = SimpleTuiProvider(
        terminal_id="t1",
        session_name="s1",
        window_name="w1",
        start_command="dummy",
        auto_accept_input="3",
    )

    mock_tmux.get_history.side_effect = [
        (
            "Do you trust the files in this folder?\n"
            "  > 3. Trust folder and all subdirectories (penn/**)\n"
            "Enter to confirm • Esc to exit\n"
        ),
        "› ",
    ]

    pane = MagicMock()
    window = MagicMock()
    window.active_pane = pane
    session = MagicMock()
    session.windows.get.return_value = window
    mock_tmux.server.sessions.get.return_value = session

    provider._handle_startup_prompts(timeout=2.0)

    pane.send_keys.assert_called_once_with("3", enter=True)


def test_has_idle_prompt_ignores_menu_choice_line():
    provider = SimpleTuiProvider(
        terminal_id="t1",
        session_name="s1",
        window_name="w1",
        start_command="dummy",
    )

    menu_output = "  > 3. Trust folder and all subdirectories (penn/**)"
    assert provider._has_idle_prompt(menu_output) is False


def test_has_idle_prompt_detects_real_prompt_line():
    provider = SimpleTuiProvider(
        terminal_id="t1",
        session_name="s1",
        window_name="w1",
        start_command="dummy",
    )

    idle_output = "\n> \n"
    assert provider._has_idle_prompt(idle_output) is True


@patch("cli_agent_orchestrator.providers.simple_tui.tmux_client")
def test_get_status_uses_grace_period_after_input(mock_tmux):
    provider = SimpleTuiProvider(
        terminal_id="t1",
        session_name="s1",
        window_name="w1",
        start_command="dummy",
    )

    mock_tmux.get_history.return_value = "> \n"
    provider.mark_input_received()
    provider._input_received_at = time.time()

    assert provider.get_status() == TerminalStatus.PROCESSING


@patch("cli_agent_orchestrator.providers.simple_tui.tmux_client")
def test_get_status_processing_when_generating_marker_present(mock_tmux):
    provider = SimpleTuiProvider(
        terminal_id="t1",
        session_name="s1",
        window_name="w1",
        start_command="dummy",
    )

    mock_tmux.get_history.return_value = "Generating...\n> \n"
    provider.mark_input_received()

    assert provider.get_status() == TerminalStatus.PROCESSING

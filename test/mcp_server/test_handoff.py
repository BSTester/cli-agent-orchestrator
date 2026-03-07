"""Tests for MCP server handoff logic."""

import asyncio
import os
from unittest.mock import MagicMock, patch

import pytest

from cli_agent_orchestrator.mcp_server import server
from cli_agent_orchestrator.mcp_server.server import _assign_impl, _handoff_impl


class TestHandoffMessageContext:
    """Tests for handoff message context prepended to worker agents."""

    @patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
    @patch("cli_agent_orchestrator.mcp_server.server.wait_until_terminal_status")
    @patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
    def test_codex_provider_prepends_handoff_context(self, mock_create, mock_wait, mock_send):
        """Codex provider should prepend [CAO Handoff] with supervisor ID."""
        mock_create.return_value = ("dev-terminal-1", "codex")
        # First call: wait for IDLE (True), second call: wait for COMPLETED (True)
        mock_wait.side_effect = [True, True]
        mock_send.return_value = None

        with patch.dict(os.environ, {"CAO_TERMINAL_ID": "supervisor-abc123"}):
            with patch("cli_agent_orchestrator.mcp_server.server.requests") as mock_requests:
                mock_response = MagicMock()
                mock_response.json.return_value = {"output": "task done"}
                mock_response.raise_for_status.return_value = None
                mock_requests.request.return_value = mock_response

                result = asyncio.get_event_loop().run_until_complete(
                    _handoff_impl("developer", "Implement hello world")
                )

        # Verify _send_direct_input was called with the handoff prefix
        mock_send.assert_called_once()
        sent_message = mock_send.call_args[0][1]
        assert sent_message.startswith("[CAO Handoff]")
        assert "supervisor-abc123" in sent_message
        assert "Implement hello world" in sent_message
        assert "Do NOT use send_message" in sent_message
        assert "Do NOT send /exit or /quit" in sent_message

    @patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
    @patch("cli_agent_orchestrator.mcp_server.server.wait_until_terminal_status")
    @patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
    def test_claude_code_provider_no_handoff_context(self, mock_create, mock_wait, mock_send):
        """Claude Code provider should NOT prepend any handoff context."""
        mock_create.return_value = ("dev-terminal-2", "claude_code")
        mock_wait.side_effect = [True, True]
        mock_send.return_value = None

        with patch("cli_agent_orchestrator.mcp_server.server.requests") as mock_requests:
            mock_response = MagicMock()
            mock_response.json.return_value = {"output": "task done"}
            mock_response.raise_for_status.return_value = None
            mock_requests.request.return_value = mock_response

            result = asyncio.get_event_loop().run_until_complete(
                _handoff_impl("developer", "Implement hello world")
            )

        # Verify message was sent unchanged
        mock_send.assert_called_once()
        sent_message = mock_send.call_args[0][1]
        assert sent_message == "Implement hello world"

    @patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
    @patch("cli_agent_orchestrator.mcp_server.server.wait_until_terminal_status")
    @patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
    def test_kiro_cli_provider_no_handoff_context(self, mock_create, mock_wait, mock_send):
        """Kiro CLI provider should NOT prepend any handoff context."""
        mock_create.return_value = ("dev-terminal-3", "kiro_cli")
        mock_wait.side_effect = [True, True]
        mock_send.return_value = None

        with patch("cli_agent_orchestrator.mcp_server.server.requests") as mock_requests:
            mock_response = MagicMock()
            mock_response.json.return_value = {"output": "task done"}
            mock_response.raise_for_status.return_value = None
            mock_requests.request.return_value = mock_response

            result = asyncio.get_event_loop().run_until_complete(
                _handoff_impl("developer", "Implement hello world")
            )

        mock_send.assert_called_once()
        sent_message = mock_send.call_args[0][1]
        assert sent_message == "Implement hello world"

    @patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
    @patch("cli_agent_orchestrator.mcp_server.server.wait_until_terminal_status")
    @patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
    def test_codex_handoff_context_includes_supervisor_id_from_env(
        self, mock_create, mock_wait, mock_send
    ):
        """Supervisor terminal ID should come from CAO_TERMINAL_ID env var."""
        mock_create.return_value = ("dev-terminal-4", "codex")
        mock_wait.side_effect = [True, True]
        mock_send.return_value = None

        with patch.dict(os.environ, {"CAO_TERMINAL_ID": "sup-xyz789"}):
            with patch("cli_agent_orchestrator.mcp_server.server.requests") as mock_requests:
                mock_response = MagicMock()
                mock_response.json.return_value = {"output": "done"}
                mock_response.raise_for_status.return_value = None
                mock_requests.request.return_value = mock_response

                asyncio.get_event_loop().run_until_complete(
                    _handoff_impl("developer", "Build feature X")
                )

        sent_message = mock_send.call_args[0][1]
        assert "sup-xyz789" in sent_message
        assert "Build feature X" in sent_message

    @patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
    @patch("cli_agent_orchestrator.mcp_server.server.wait_until_terminal_status")
    @patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
    @patch("cli_agent_orchestrator.mcp_server.server._current_terminal_id")
    def test_codex_handoff_context_fallback_when_no_env(
        self, mock_current_terminal_id, mock_create, mock_wait, mock_send
    ):
        """When CAO_TERMINAL_ID is not set, supervisor ID should be 'unknown'."""
        mock_create.return_value = ("dev-terminal-5", "codex")
        mock_wait.side_effect = [True, True]
        mock_send.return_value = None
        mock_current_terminal_id.side_effect = ValueError("CAO_TERMINAL_ID not set")

        with patch.dict(os.environ, {}, clear=True):
            with patch("cli_agent_orchestrator.mcp_server.server.requests") as mock_requests:
                mock_response = MagicMock()
                mock_response.json.return_value = {"output": "done"}
                mock_response.raise_for_status.return_value = None
                mock_requests.request.return_value = mock_response

                asyncio.get_event_loop().run_until_complete(_handoff_impl("developer", "Do task"))

        sent_message = mock_send.call_args[0][1]
        assert "unknown" in sent_message
        assert "[CAO Handoff]" in sent_message
        assert "Do task" in sent_message

    @patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
    @patch("cli_agent_orchestrator.mcp_server.server.wait_until_terminal_status")
    @patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
    def test_codex_handoff_original_message_preserved(self, mock_create, mock_wait, mock_send):
        """Original message should appear in full after the handoff prefix."""
        mock_create.return_value = ("dev-terminal-6", "codex")
        mock_wait.side_effect = [True, True]
        mock_send.return_value = None

        original = "Implement the task described in /path/to/task.md. Write tests."
        with patch.dict(os.environ, {"CAO_TERMINAL_ID": "sup-111"}):
            with patch("cli_agent_orchestrator.mcp_server.server.requests") as mock_requests:
                mock_response = MagicMock()
                mock_response.json.return_value = {"output": "done"}
                mock_response.raise_for_status.return_value = None
                mock_requests.request.return_value = mock_response

                asyncio.get_event_loop().run_until_complete(_handoff_impl("developer", original))

        sent_message = mock_send.call_args[0][1]
        assert sent_message.endswith(original)


def test_current_terminal_id_falls_back_to_tmux(monkeypatch):
    """Fallback should read CAO_TERMINAL_ID from tmux environment when env var is missing."""
    monkeypatch.delenv("CAO_TERMINAL_ID", raising=False)
    fake_run = MagicMock()
    fake_run.return_value = MagicMock(stdout="CAO_TERMINAL_ID=tmux-123\n", returncode=0)
    monkeypatch.setattr(server.subprocess, "run", fake_run)

    assert server._current_terminal_id() == "tmux-123"


@patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
@patch("cli_agent_orchestrator.mcp_server.server.wait_until_terminal_status")
@patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
def test_handoff_expands_terminal_placeholder(mock_create, mock_wait, mock_send):
    mock_create.return_value = ("dev-terminal-9", "codex")
    mock_wait.side_effect = [True, True]
    mock_send.return_value = None

    with patch.dict(os.environ, {"CAO_TERMINAL_ID": "my-term"}):
        with patch("cli_agent_orchestrator.mcp_server.server.requests") as mock_requests:
            mock_response = MagicMock()
            mock_response.json.return_value = {"output": "done"}
            mock_response.raise_for_status.return_value = None
            mock_requests.request.return_value = mock_response

            asyncio.get_event_loop().run_until_complete(
                server._handoff_impl(
                    "developer",
                    "Return to ${CAO_TERMINAL_ID}",
                    timeout=600,
                    working_directory=None,
                    provider="codex",
                )
            )

    sent_message = mock_send.call_args[0][1]
    assert "my-term" in sent_message
    assert "${CAO_TERMINAL_ID}" not in sent_message


@patch("cli_agent_orchestrator.mcp_server.server._request_with_retry")
@patch("cli_agent_orchestrator.mcp_server.server._fetch_stable_handoff_output")
@patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
@patch("cli_agent_orchestrator.mcp_server.server.wait_until_terminal_status")
@patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
def test_handoff_keeps_worker_terminal_online(
    mock_create,
    mock_wait,
    mock_send,
    mock_fetch_output,
    mock_request,
):
    mock_create.return_value = ("dev-terminal-keep", "codex")
    mock_wait.side_effect = [True, True]
    mock_fetch_output.return_value = "task done"

    result = asyncio.get_event_loop().run_until_complete(
        server._handoff_impl("developer", "Implement hello world")
    )

    assert result.success is True
    assert result.terminal_id == "dev-terminal-keep"
    mock_request.assert_not_called()


@patch("cli_agent_orchestrator.mcp_server.server.wait_until_terminal_status")
@patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
@patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
def test_assign_fails_when_terminal_not_ready(mock_create, mock_send, mock_wait):
    """Assign should fail fast if worker terminal never reaches ready status."""
    mock_create.return_value = ("dev-terminal-7", "kiro_cli")
    mock_wait.return_value = False

    result = _assign_impl("developer", "Do work")

    assert result["success"] is False
    assert result["terminal_id"] == "dev-terminal-7"
    assert "did not become ready" in result["message"]
    mock_send.assert_not_called()


def test_assign_fails_when_message_is_blank():
    result = _assign_impl("developer", "   ")

    assert result["success"] is False
    assert result["terminal_id"] is None
    assert "message cannot be empty" in result["message"]


@patch("cli_agent_orchestrator.mcp_server.server.time.sleep")
@patch("cli_agent_orchestrator.mcp_server.server.wait_until_terminal_status")
@patch("cli_agent_orchestrator.mcp_server.server._send_to_inbox")
@patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
@patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
def test_assign_replaces_terminal_placeholder(
    mock_create,
    mock_send,
    mock_send_inbox,
    mock_wait,
    mock_sleep,
):
    mock_create.return_value = ("dev-terminal-10", "kiro_cli")
    mock_wait.return_value = True
    mock_send_inbox.return_value = {"success": True}

    with patch.dict(os.environ, {"CAO_TERMINAL_ID": "abc999"}):
        result = _assign_impl("developer", "Notify ${CAO_TERMINAL_ID}")

    assert result["success"] is True
    send_args = mock_send_inbox.call_args[0]
    assert send_args[1] == "Notify abc999"


@patch("cli_agent_orchestrator.mcp_server.server.time.sleep")
@patch("cli_agent_orchestrator.mcp_server.server.wait_until_terminal_status")
@patch("cli_agent_orchestrator.mcp_server.server._send_to_inbox")
@patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
@patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
def test_assign_replaces_double_brace_terminal_placeholder(
    mock_create,
    mock_send,
    mock_send_inbox,
    mock_wait,
    mock_sleep,
):
    mock_create.return_value = ("dev-terminal-11", "kiro_cli")
    mock_wait.return_value = True
    mock_send_inbox.return_value = {"success": True}

    with patch.dict(os.environ, {"CAO_TERMINAL_ID": "xyz123"}):
        result = _assign_impl("developer", "Ping {{CAO_TERMINAL_ID}}")

    assert result["success"] is True
    send_args = mock_send_inbox.call_args[0]
    assert send_args[1] == "Ping xyz123"


@patch("cli_agent_orchestrator.mcp_server.server.time.sleep")
@patch("cli_agent_orchestrator.mcp_server.server.wait_until_terminal_status")
@patch("cli_agent_orchestrator.mcp_server.server._send_to_inbox")
@patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
@patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
def test_assign_waits_stabilization_before_sending(
    mock_create,
    mock_send,
    mock_send_inbox,
    mock_wait,
    mock_sleep,
):
    mock_create.return_value = ("dev-terminal-8", "kiro_cli")
    mock_wait.return_value = True

    result = _assign_impl("developer", "Do work")

    assert result["success"] is True
    mock_sleep.assert_any_call(2.0)
    mock_send_inbox.assert_called_once_with("dev-terminal-8", "Do work")
    mock_send.assert_not_called()


@patch("cli_agent_orchestrator.mcp_server.server.time.sleep")
@patch("cli_agent_orchestrator.mcp_server.server.wait_until_terminal_status")
@patch("cli_agent_orchestrator.mcp_server.server._send_to_inbox")
@patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
@patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
def test_assign_does_not_resend_when_initial_inbox_send_succeeds(
    mock_create,
    mock_send,
    mock_send_inbox,
    mock_wait,
    mock_sleep,
):
    mock_create.return_value = ("dev-terminal-9", "kiro_cli")
    mock_wait.return_value = True

    result = _assign_impl("developer", "Do work")

    assert result["success"] is True
    mock_send_inbox.assert_called_once_with("dev-terminal-9", "Do work")
    mock_send.assert_not_called()


@patch("cli_agent_orchestrator.mcp_server.server.time.sleep")
@patch("cli_agent_orchestrator.mcp_server.server.wait_until_terminal_status")
@patch("cli_agent_orchestrator.mcp_server.server._send_to_inbox")
@patch("cli_agent_orchestrator.mcp_server.server._send_direct_input")
@patch("cli_agent_orchestrator.mcp_server.server._create_terminal")
def test_assign_fallbacks_to_direct_input_if_inbox_send_fails(
    mock_create,
    mock_send,
    mock_send_inbox,
    mock_wait,
    mock_sleep,
):
    mock_create.return_value = ("dev-terminal-10", "kiro_cli")
    mock_wait.return_value = True
    mock_send_inbox.side_effect = ValueError("CAO_TERMINAL_ID not set")

    result = _assign_impl("developer", "Do work")

    assert result["success"] is True
    mock_send.assert_called_once_with("dev-terminal-10", "Do work")
    mock_send_inbox.assert_called_once_with("dev-terminal-10", "Do work")


@patch("cli_agent_orchestrator.mcp_server.server.time.sleep")
@patch("cli_agent_orchestrator.mcp_server.server._create_terminal_with_retry")
@patch("cli_agent_orchestrator.mcp_server.server._send_to_inbox")
def test_assign_reuses_existing_terminal_when_available(
    mock_send_inbox, mock_create, mock_sleep
):
    """Assign should reuse an existing worker with the same profile in session."""
    mock_send_inbox.return_value = {"success": True}
    mock_create.side_effect = AssertionError("Should not create a new terminal")

    metadata_resp = MagicMock()
    metadata_resp.json.return_value = {"session_name": "session-1", "provider": "codex"}

    list_resp = MagicMock()
    list_resp.json.return_value = [
        {"id": "worker-1111", "agent_profile": "designer", "provider": "codex"},
        {"id": "leader-0000", "agent_profile": "supervisor", "provider": "codex"},
    ]

    status_resp = MagicMock()
    status_resp.json.return_value = {"status": "processing"}

    with patch.dict(os.environ, {"CAO_TERMINAL_ID": "leader-0000"}):
        with patch(
            "cli_agent_orchestrator.mcp_server.server._request_with_retry",
            side_effect=[metadata_resp, list_resp, status_resp],
        ):
            result = _assign_impl("designer", "Draft a landing page")

    assert result["success"] is True
    assert result["terminal_id"] == "worker-1111"
    assert "codex" in result["message"]
    mock_send_inbox.assert_called_once_with("worker-1111", "Draft a landing page")
    mock_create.assert_not_called()
    mock_sleep.assert_not_called()


@patch("cli_agent_orchestrator.mcp_server.server._send_to_inbox")
def test_send_message_no_auto_cleanup(mock_send_to_inbox):
    mock_send_to_inbox.return_value = {"success": True, "message_id": 102}
    result = server._send_message_impl("worker-1", "please continue")

    assert result["success"] is True
    assert "auto_cleanup" not in result
    mock_send_to_inbox.assert_called_once_with("worker-1", "please continue")


@patch("cli_agent_orchestrator.mcp_server.server.time.sleep")
@patch("cli_agent_orchestrator.mcp_server.server._request_with_retry")
def test_fetch_stable_handoff_output_waits_for_non_transient_text(
    mock_request_with_retry,
    mock_sleep,
):
    transient_resp = MagicMock()
    transient_resp.json.return_value = {"output": "Generating..."}

    final_resp = MagicMock()
    final_resp.json.return_value = {"output": "Implementation completed successfully"}

    mock_request_with_retry.side_effect = [transient_resp, final_resp]

    output = server._fetch_stable_handoff_output("worker-1", timeout_seconds=120)

    assert output == "Implementation completed successfully"
    assert mock_request_with_retry.call_count == 2

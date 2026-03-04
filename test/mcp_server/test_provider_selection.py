"""Tests for provider selection in MCP server terminal creation."""

import os
from unittest.mock import MagicMock, patch

from cli_agent_orchestrator.constants import DEFAULT_PROVIDER
from cli_agent_orchestrator.mcp_server.server import _create_terminal
from cli_agent_orchestrator.models.provider import ProviderType


@patch("cli_agent_orchestrator.mcp_server.server.requests.request")
def test_create_terminal_uses_explicit_provider_override(mock_request):
    metadata_response = MagicMock()
    metadata_response.raise_for_status.return_value = None
    metadata_response.json.return_value = {
        "provider": "kiro_cli",
        "session_name": "cao-test-session",
    }

    create_response = MagicMock()
    create_response.raise_for_status.return_value = None
    create_response.json.return_value = {"id": "term1234"}

    list_response = MagicMock()
    list_response.raise_for_status.return_value = None
    list_response.json.return_value = []

    mock_request.side_effect = [metadata_response, list_response, create_response]

    with patch.dict(os.environ, {"CAO_TERMINAL_ID": "abc12345"}):
        terminal_id, provider = _create_terminal(
            "developer",
            working_directory="/tmp/project",
            provider=ProviderType.COPILOT.value,
        )

    assert terminal_id == "term1234"
    assert provider == ProviderType.COPILOT.value
    assert mock_request.call_args.kwargs["params"]["provider"] == ProviderType.COPILOT.value


@patch("cli_agent_orchestrator.mcp_server.server._request_with_retry")
def test_create_terminal_uses_single_attempt_for_creation(mock_request):
    metadata_response = MagicMock()
    metadata_response.raise_for_status.return_value = None
    metadata_response.json.return_value = {
        "provider": "kiro_cli",
        "session_name": "cao-test-session",
    }

    working_dir_response = MagicMock()
    working_dir_response.raise_for_status.return_value = None
    working_dir_response.json.return_value = {"working_directory": "/home/runner/project"}

    create_response = MagicMock()
    create_response.raise_for_status.return_value = None
    create_response.json.return_value = {"id": "term2345"}

    list_response = MagicMock()
    list_response.raise_for_status.return_value = None
    list_response.json.return_value = []

    mock_request.side_effect = [metadata_response, working_dir_response, list_response, create_response]

    with patch.dict(os.environ, {"CAO_TERMINAL_ID": "abc12345"}):
        terminal_id, provider = _create_terminal("developer")

    assert terminal_id == "term2345"
    assert provider == "kiro_cli"
    assert mock_request.call_args_list[3].kwargs.get("retry_attempts") == 1


@patch("cli_agent_orchestrator.mcp_server.server.requests.request")
@patch("cli_agent_orchestrator.mcp_server.server.load_agent_profile")
def test_create_terminal_uses_profile_provider_when_no_override(mock_load_profile, mock_request):
    profile = type("Profile", (), {"provider": ProviderType.COPILOT})()
    mock_load_profile.return_value = profile

    metadata_response = MagicMock()
    metadata_response.raise_for_status.return_value = None
    metadata_response.json.return_value = {
        "provider": "kiro_cli",
        "session_name": "cao-test-session",
    }

    create_response = MagicMock()
    create_response.raise_for_status.return_value = None
    create_response.json.return_value = {"id": "term5678"}

    list_response = MagicMock()
    list_response.raise_for_status.return_value = None
    list_response.json.return_value = []

    mock_request.side_effect = [metadata_response, list_response, create_response]

    with patch.dict(os.environ, {"CAO_TERMINAL_ID": "abc12345"}):
        terminal_id, provider = _create_terminal("developer", working_directory="/tmp/project")

    assert terminal_id == "term5678"
    assert provider == ProviderType.COPILOT.value
    assert mock_request.call_args.kwargs["params"]["provider"] == ProviderType.COPILOT.value


@patch("cli_agent_orchestrator.mcp_server.server.requests.request")
@patch(
    "cli_agent_orchestrator.mcp_server.server.generate_session_name",
    return_value="cao-test-session",
)
@patch("cli_agent_orchestrator.mcp_server.server.load_agent_profile")
def test_create_terminal_falls_back_to_default_provider_in_new_session(
    mock_load_profile, mock_gen_session, mock_request
):
    mock_load_profile.side_effect = RuntimeError("Profile not found")

    create_response = MagicMock()
    create_response.raise_for_status.return_value = None
    create_response.json.return_value = {"id": "term9012"}
    mock_request.return_value = create_response

    with patch.dict(os.environ, {}, clear=True):
        terminal_id, provider = _create_terminal("developer")

    assert terminal_id == "term9012"
    assert provider == DEFAULT_PROVIDER
    assert "provider" not in mock_request.call_args.kwargs["params"]


@patch("cli_agent_orchestrator.mcp_server.server.requests.request")
@patch("cli_agent_orchestrator.mcp_server.server.load_agent_profile")
def test_create_terminal_treats_empty_provider_as_none(mock_load_profile, mock_request):
    profile = type("Profile", (), {"provider": ProviderType.CLAUDE_CODE})()
    mock_load_profile.return_value = profile

    metadata_response = MagicMock()
    metadata_response.raise_for_status.return_value = None
    metadata_response.json.return_value = {
        "provider": "kiro_cli",
        "session_name": "cao-test-session",
    }

    working_dir_response = MagicMock()
    working_dir_response.raise_for_status.return_value = None
    working_dir_response.json.return_value = {"working_directory": "/home/runner/workspace"}

    list_response = MagicMock()
    list_response.raise_for_status.return_value = None
    list_response.json.return_value = []

    create_response = MagicMock()
    create_response.raise_for_status.return_value = None
    create_response.json.return_value = {"id": "term7777"}

    mock_request.side_effect = [metadata_response, working_dir_response, list_response, create_response]

    with patch.dict(os.environ, {"CAO_TERMINAL_ID": "abc12345"}):
        terminal_id, provider = _create_terminal("developer", provider=" ")

    assert terminal_id == "term7777"
    assert provider == ProviderType.CLAUDE_CODE.value
    assert mock_request.call_args.kwargs["params"]["provider"] == ProviderType.CLAUDE_CODE.value


@patch("cli_agent_orchestrator.mcp_server.server.requests.request")
@patch("cli_agent_orchestrator.mcp_server.server.load_agent_profile")
def test_create_terminal_reuses_idle_existing_worker(mock_load_profile, mock_request):
    profile = type("Profile", (), {"provider": ProviderType.KIRO_CLI})()
    mock_load_profile.return_value = profile

    metadata_response = MagicMock()
    metadata_response.raise_for_status.return_value = None
    metadata_response.json.return_value = {
        "provider": "kiro_cli",
        "session_name": "cao-test-session",
    }

    working_dir_response = MagicMock()
    working_dir_response.raise_for_status.return_value = None
    working_dir_response.json.return_value = {"working_directory": "/home/runner/workspace"}

    list_response = MagicMock()
    list_response.raise_for_status.return_value = None
    list_response.json.return_value = [
        {
            "id": "idle1234",
            "provider": "kiro_cli",
            "agent_profile": "developer",
            "tmux_session": "cao-test-session",
            "tmux_window": "dev-1",
        }
    ]

    status_response = MagicMock()
    status_response.raise_for_status.return_value = None
    status_response.json.return_value = {"status": "idle"}

    mock_request.side_effect = [
        metadata_response,
        working_dir_response,
        list_response,
        status_response,
    ]

    with patch.dict(os.environ, {"CAO_TERMINAL_ID": "abc12345"}):
        terminal_id, provider = _create_terminal("developer")

    assert terminal_id == "idle1234"
    assert provider == ProviderType.KIRO_CLI.value
    # Ensure we never issued a POST create call
    assert mock_request.call_args_list[-1].kwargs["url"].endswith("/idle1234")

import pytest
import requests

from cli_agent_orchestrator.mcp_server import server


def test_create_terminal_with_retry_succeeds_after_failures(monkeypatch):
    """Creates terminal without retry and returns underlying result."""
    attempts: list[None] = []

    def fake_create(agent_profile: str, working_directory=None, provider=None):
        attempts.append(None)
        return "terminal-id", "provider-name"

    monkeypatch.setattr(server, "_create_terminal", fake_create)

    terminal_id, provider = server._create_terminal_with_retry("dev")

    assert terminal_id == "terminal-id"
    assert provider == "provider-name"
    assert len(attempts) == 1


def test_create_terminal_with_retry_stops_after_limit(monkeypatch):
    """Errors propagate immediately without retry."""
    attempts: list[None] = []

    def always_fail(agent_profile: str, working_directory=None, provider=None):
        attempts.append(None)
        raise RuntimeError("fail")

    monkeypatch.setattr(server, "_create_terminal", always_fail)

    with pytest.raises(RuntimeError):
        server._create_terminal_with_retry("dev")

    assert len(attempts) == 1


def test_create_terminal_with_retry_no_retry_on_http_error(monkeypatch):
    """HTTP errors also do not retry."""
    attempts: list[None] = []

    def http_error(agent_profile: str, working_directory=None, provider=None):
        attempts.append(None)
        raise requests.HTTPError("500 server error")

    monkeypatch.setattr(server, "_create_terminal", http_error)

    with pytest.raises(requests.HTTPError):
        server._create_terminal_with_retry("dev")

    assert len(attempts) == 1

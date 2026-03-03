import pytest

from cli_agent_orchestrator.mcp_server import server


def test_create_terminal_with_retry_succeeds_after_failures(monkeypatch):
    """Ensure worker creation retries are bounded and succeed before the limit."""
    attempts: list[None] = []
    max_attempts = server.WORK_AGENT_CREATE_RETRY_ATTEMPTS

    def fake_create(agent_profile: str, working_directory=None, provider=None):
        attempts.append(None)
        if len(attempts) < max_attempts:
            raise RuntimeError("boom")
        return "terminal-id", "provider-name"

    monkeypatch.setattr(server, "_create_terminal", fake_create)
    monkeypatch.setattr(server.time, "sleep", lambda *_: None)

    terminal_id, provider = server._create_terminal_with_retry("dev")

    assert terminal_id == "terminal-id"
    assert provider == "provider-name"
    assert len(attempts) == max_attempts


def test_create_terminal_with_retry_stops_after_limit(monkeypatch):
    """Ensure worker creation errors stop after the configured retry cap."""
    attempts: list[None] = []

    def always_fail(agent_profile: str, working_directory=None, provider=None):
        attempts.append(None)
        raise RuntimeError("fail")

    monkeypatch.setattr(server, "_create_terminal", always_fail)
    monkeypatch.setattr(server.time, "sleep", lambda *_: None)

    with pytest.raises(RuntimeError):
        server._create_terminal_with_retry("dev")

    assert len(attempts) == server.WORK_AGENT_CREATE_RETRY_ATTEMPTS

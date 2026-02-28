"""Tests for the control panel FastAPI interface layer."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests
from fastapi.testclient import TestClient

from cli_agent_orchestrator.control_panel.main import CONSOLE_PASSWORD, app


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the control panel app."""
    return TestClient(app)


def login(client: TestClient) -> None:
    response = client.post("/auth/login", json={"password": CONSOLE_PASSWORD})
    assert response.status_code == 200


def test_health_endpoint_success(client: TestClient) -> None:
    """Test health endpoint when cao-server is reachable."""
    with patch("cli_agent_orchestrator.control_panel.main.requests.get") as mock_get:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["cao_server_status"] == "healthy"


def test_health_endpoint_cao_unreachable(client: TestClient) -> None:
    """Test health endpoint when cao-server is unreachable."""
    with patch("cli_agent_orchestrator.control_panel.main.requests.get") as mock_get:
        mock_get.side_effect = requests.exceptions.ConnectionError()

        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["cao_server_status"] == "unreachable"


def test_auth_login_and_me(client: TestClient) -> None:
    response = client.post("/auth/login", json={"password": CONSOLE_PASSWORD})
    assert response.status_code == 200

    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["authenticated"] is True


def test_auth_required_for_proxy_routes(client: TestClient) -> None:
    response = client.get("/sessions")
    assert response.status_code == 401


def test_proxy_get_request(client: TestClient) -> None:
    """Test proxying a GET request to cao-server."""
    login(client)

    with patch("cli_agent_orchestrator.control_panel.main.requests.request") as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"result": "success"}'
        mock_response.headers = {"Content-Type": "application/json"}
        mock_request.return_value = mock_response

        response = client.get("/sessions")

        assert response.status_code == 200
        assert response.headers.get("x-request-id")
        call_headers = mock_request.call_args.kwargs["headers"]
        assert call_headers.get("X-Request-Id")
        mock_request.assert_called_once()


def test_proxy_post_request(client: TestClient) -> None:
    """Test proxying a POST request to cao-server."""
    login(client)

    with patch("cli_agent_orchestrator.control_panel.main.requests.request") as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.content = b'{"id": "test123"}'
        mock_response.headers = {"Content-Type": "application/json"}
        mock_request.return_value = mock_response

        response = client.post("/sessions", json={"agent_profile": "test", "provider": "kiro_cli"})

        assert response.status_code == 201
        mock_request.assert_called_once()


def test_proxy_handles_cao_server_error(client: TestClient) -> None:
    """Test proxy handles cao-server connection errors."""
    login(client)

    with patch("cli_agent_orchestrator.control_panel.main.requests.request") as mock_request:
        mock_request.side_effect = requests.exceptions.ConnectionError("Connection failed")

        response = client.get("/sessions")

        assert response.status_code == 502
        data = response.json()
        assert "Failed to reach cao-server" in data["detail"]


def test_proxy_forwards_query_parameters(client: TestClient) -> None:
    """Test proxy forwards query parameters to cao-server."""
    login(client)

    with patch("cli_agent_orchestrator.control_panel.main.requests.request") as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"[]"
        mock_response.headers = {}
        mock_request.return_value = mock_response

        client.get("/sessions?limit=10&offset=20")

        call_args = mock_request.call_args
        assert "limit=10" in call_args.kwargs["url"]
        assert "offset=20" in call_args.kwargs["url"]


def test_console_overview(client: TestClient) -> None:
    login(client)

    with patch("cli_agent_orchestrator.control_panel.main.requests.request") as mock_request:
        sessions = MagicMock()
        sessions.raise_for_status.return_value = None
        sessions.json.return_value = [{"name": "cao-abc"}]

        terminals = MagicMock()
        terminals.raise_for_status.return_value = None
        terminals.json.return_value = [
            {
                "id": "term1",
                "provider": "kiro_cli",
                "agent_profile": "code_supervisor",
                "session_name": "cao-abc",
            }
        ]

        terminal_detail = MagicMock()
        terminal_detail.raise_for_status.return_value = None
        terminal_detail.json.return_value = {
            "id": "term1",
            "status": "IDLE",
            "provider": "kiro_cli",
            "agent_profile": "code_supervisor",
            "session_name": "cao-abc",
        }

        mock_request.side_effect = [sessions, terminals, terminal_detail]

        response = client.get("/console/overview")

        assert response.status_code == 200
        data = response.json()
        assert data["agents_total"] == 1
        assert data["main_agents_total"] == 1
        assert data["provider_counts"]["kiro_cli"] == 1


def test_console_agent_input_wrapper(client: TestClient) -> None:
    login(client)

    with patch("cli_agent_orchestrator.control_panel.main.requests.request") as mock_request:
        sent = MagicMock()
        sent.raise_for_status.return_value = None
        sent.json.return_value = {"success": True}
        mock_request.return_value = sent

        response = client.post("/console/agents/abc123/input", json={"message": "hello"})

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["terminal_id"] == "abc123"


def test_console_organization_two_layers(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._list_worker_links", return_value={"worker1": "leader1"}),
        patch("cli_agent_orchestrator.control_panel.main._register_team"),
        patch("cli_agent_orchestrator.control_panel.main._set_worker_link"),
        patch("cli_agent_orchestrator.control_panel.main.requests.request") as mock_request,
    ):
        sessions = MagicMock()
        sessions.raise_for_status.return_value = None
        sessions.json.return_value = [{"name": "cao-team1"}]

        terminals = MagicMock()
        terminals.raise_for_status.return_value = None
        terminals.json.return_value = [
            {
                "id": "leader1",
                "provider": "kiro_cli",
                "agent_profile": "code_supervisor",
                "session_name": "cao-team1",
            },
            {
                "id": "worker1",
                "provider": "codex",
                "agent_profile": "developer",
                "session_name": "cao-team1",
            },
        ]

        leader_detail = MagicMock()
        leader_detail.raise_for_status.return_value = None
        leader_detail.json.return_value = {
            "id": "leader1",
            "status": "IDLE",
            "provider": "kiro_cli",
            "agent_profile": "code_supervisor",
            "session_name": "cao-team1",
        }

        worker_detail = MagicMock()
        worker_detail.raise_for_status.return_value = None
        worker_detail.json.return_value = {
            "id": "worker1",
            "status": "PROCESSING",
            "provider": "codex",
            "agent_profile": "developer",
            "session_name": "cao-team1",
        }

        mock_request.side_effect = [sessions, terminals, leader_detail, worker_detail]

        response = client.get("/console/organization")

        assert response.status_code == 200
        body = response.json()
        assert body["leaders_total"] == 1
        assert body["workers_total"] == 1
        assert len(body["leader_groups"]) == 1
        assert body["leader_groups"][0]["leader"]["id"] == "leader1"
        assert body["leader_groups"][0]["members"][0]["id"] == "worker1"


def test_console_organization_infers_worker_link_from_inbox(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._list_worker_links", return_value={}),
        patch("cli_agent_orchestrator.control_panel.main._list_teams", return_value=set()),
        patch("cli_agent_orchestrator.control_panel.main._list_team_aliases", return_value={}),
        patch("cli_agent_orchestrator.control_panel.main._list_agent_aliases", return_value={}),
        patch(
            "cli_agent_orchestrator.control_panel.main._infer_worker_leader_links_from_inbox",
            return_value={"worker2": "leader1"},
        ),
        patch("cli_agent_orchestrator.control_panel.main._register_team"),
        patch("cli_agent_orchestrator.control_panel.main._set_worker_link") as mock_set_worker_link,
        patch("cli_agent_orchestrator.control_panel.main.requests.request") as mock_request,
    ):
        sessions = MagicMock()
        sessions.raise_for_status.return_value = None
        sessions.json.return_value = [{"name": "cao-leader"}, {"name": "cao-worker"}]

        leader_session_terminals = MagicMock()
        leader_session_terminals.raise_for_status.return_value = None
        leader_session_terminals.json.return_value = [
            {
                "id": "leader1",
                "provider": "kiro_cli",
                "agent_profile": "code_supervisor",
                "session_name": "cao-leader",
            }
        ]

        worker_session_terminals = MagicMock()
        worker_session_terminals.raise_for_status.return_value = None
        worker_session_terminals.json.return_value = [
            {
                "id": "worker2",
                "provider": "codex",
                "agent_profile": "developer",
                "session_name": "cao-worker",
            }
        ]

        leader_detail = MagicMock()
        leader_detail.raise_for_status.return_value = None
        leader_detail.json.return_value = {
            "id": "leader1",
            "status": "IDLE",
            "provider": "kiro_cli",
            "agent_profile": "code_supervisor",
            "session_name": "cao-leader",
        }

        worker_detail = MagicMock()
        worker_detail.raise_for_status.return_value = None
        worker_detail.json.return_value = {
            "id": "worker2",
            "status": "PROCESSING",
            "provider": "codex",
            "agent_profile": "developer",
            "session_name": "cao-worker",
        }

        mock_request.side_effect = [
            sessions,
            leader_session_terminals,
            worker_session_terminals,
            leader_detail,
            worker_detail,
        ]

        response = client.get("/console/organization")

        assert response.status_code == 200
        body = response.json()
        assert len(body["leader_groups"]) == 1
        assert body["leader_groups"][0]["leader"]["id"] == "leader1"
        assert body["leader_groups"][0]["members"][0]["id"] == "worker2"
        mock_set_worker_link.assert_called_once_with("worker2", "leader1")


def test_console_organization_single_leader_fallback_assigns_unlinked_workers(
    client: TestClient,
) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._list_worker_links", return_value={}),
        patch("cli_agent_orchestrator.control_panel.main._list_teams", return_value=set()),
        patch("cli_agent_orchestrator.control_panel.main._list_team_aliases", return_value={}),
        patch("cli_agent_orchestrator.control_panel.main._list_agent_aliases", return_value={}),
        patch(
            "cli_agent_orchestrator.control_panel.main._infer_worker_leader_links_from_inbox",
            return_value={},
        ),
        patch(
            "cli_agent_orchestrator.control_panel.main._infer_worker_leader_links_from_session_name",
            return_value={},
        ),
        patch("cli_agent_orchestrator.control_panel.main._register_team"),
        patch("cli_agent_orchestrator.control_panel.main._set_worker_link") as mock_set_worker_link,
        patch("cli_agent_orchestrator.control_panel.main.requests.request") as mock_request,
    ):
        sessions = MagicMock()
        sessions.raise_for_status.return_value = None
        sessions.json.return_value = [{"name": "cao-main"}, {"name": "cao-remote-worker"}]

        leader_session_terminals = MagicMock()
        leader_session_terminals.raise_for_status.return_value = None
        leader_session_terminals.json.return_value = [
            {
                "id": "leader1",
                "provider": "claude_code",
                "agent_profile": "code_supervisor",
                "session_name": "cao-main",
            }
        ]

        worker_session_terminals = MagicMock()
        worker_session_terminals.raise_for_status.return_value = None
        worker_session_terminals.json.return_value = [
            {
                "id": "worker3",
                "provider": "claude_code",
                "agent_profile": "developer",
                "session_name": "cao-remote-worker",
            }
        ]

        leader_detail = MagicMock()
        leader_detail.raise_for_status.return_value = None
        leader_detail.json.return_value = {
            "id": "leader1",
            "status": "IDLE",
            "provider": "claude_code",
            "agent_profile": "code_supervisor",
            "session_name": "cao-main",
        }

        worker_detail = MagicMock()
        worker_detail.raise_for_status.return_value = None
        worker_detail.json.return_value = {
            "id": "worker3",
            "status": "IDLE",
            "provider": "claude_code",
            "agent_profile": "developer",
            "session_name": "cao-remote-worker",
        }

        mock_request.side_effect = [
            sessions,
            leader_session_terminals,
            worker_session_terminals,
            leader_detail,
            worker_detail,
        ]

        response = client.get("/console/organization")

        assert response.status_code == 200
        body = response.json()
        assert len(body["leader_groups"]) == 1
        assert body["leader_groups"][0]["leader"]["id"] == "leader1"
        assert body["leader_groups"][0]["members"][0]["id"] == "worker3"
        mock_set_worker_link.assert_called_once_with("worker3", "leader1")


def test_console_create_org_worker_linked_to_leader(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._register_team") as mock_register_team,
        patch("cli_agent_orchestrator.control_panel.main._set_worker_link") as mock_set_worker_link,
        patch("cli_agent_orchestrator.control_panel.main.requests.request") as mock_request,
    ):
        leader = MagicMock()
        leader.raise_for_status.return_value = None
        leader.json.return_value = {
            "id": "leader1",
            "agent_profile": "code_supervisor",
            "session_name": "cao-team1",
        }

        created = MagicMock()
        created.raise_for_status.return_value = None
        created.json.return_value = {
            "id": "worker1",
            "agent_profile": "developer",
            "session_name": "cao-team1",
        }

        mock_request.side_effect = [leader, created]

        response = client.post(
            "/console/organization/create",
            json={
                "role_type": "worker",
                "agent_profile": "developer",
                "leader_id": "leader1",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["leader_id"] == "leader1"
        mock_register_team.assert_called_once_with("leader1")
        mock_set_worker_link.assert_called_once_with("worker1", "leader1")


def test_console_create_org_worker_without_leader_becomes_team(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._register_team") as mock_register_team,
        patch("cli_agent_orchestrator.control_panel.main.requests.request") as mock_request,
    ):
        created = MagicMock()
        created.raise_for_status.return_value = None
        created.json.return_value = {
            "id": "worker-team-1",
            "agent_profile": "developer",
            "session_name": "cao-worker-team-1",
        }
        mock_request.return_value = created

        response = client.post(
            "/console/organization/create",
            json={
                "role_type": "worker",
                "agent_profile": "developer",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["leader_id"] == "worker-team-1"
        mock_register_team.assert_called_once_with("worker-team-1")


def test_console_create_main_team_with_alias(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._register_team") as mock_register_team,
        patch("cli_agent_orchestrator.control_panel.main._set_team_alias") as mock_set_team_alias,
        patch("cli_agent_orchestrator.control_panel.main.requests.request") as mock_request,
    ):
        created = MagicMock()
        created.raise_for_status.return_value = None
        created.json.return_value = {
            "id": "leader-main-1",
            "agent_profile": "code_supervisor",
            "session_name": "cao-main-1",
        }
        mock_request.return_value = created

        response = client.post(
            "/console/organization/create",
            json={
                "role_type": "main",
                "agent_profile": "code_supervisor",
                "team_alias": "产品技术团队",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        mock_register_team.assert_called_once_with("leader-main-1")
        mock_set_team_alias.assert_called_once_with("leader-main-1", "产品技术团队")


def test_console_create_org_worker_with_agent_alias(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._register_team") as mock_register_team,
        patch("cli_agent_orchestrator.control_panel.main._set_worker_link") as mock_set_worker_link,
        patch("cli_agent_orchestrator.control_panel.main._set_agent_alias") as mock_set_agent_alias,
        patch("cli_agent_orchestrator.control_panel.main.requests.request") as mock_request,
    ):
        leader = MagicMock()
        leader.raise_for_status.return_value = None
        leader.json.return_value = {
            "id": "leader1",
            "agent_profile": "code_supervisor",
            "session_name": "cao-team1",
        }

        created = MagicMock()
        created.raise_for_status.return_value = None
        created.json.return_value = {
            "id": "worker1",
            "agent_profile": "developer",
            "session_name": "cao-team1",
        }

        mock_request.side_effect = [leader, created]

        response = client.post(
            "/console/organization/create",
            json={
                "role_type": "worker",
                "agent_profile": "developer",
                "leader_id": "leader1",
                "agent_alias": "后端工程师-A",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        mock_register_team.assert_called_once_with("leader1")
        mock_set_worker_link.assert_called_once_with("worker1", "leader1")
        mock_set_agent_alias.assert_called_once_with("worker1", "后端工程师-A")


def test_console_create_org_agent_propagates_upstream_http_error(client: TestClient) -> None:
    login(client)

    with patch("cli_agent_orchestrator.control_panel.main.requests.request") as mock_request:
        upstream_response = requests.Response()
        upstream_response.status_code = 400
        upstream_response._content = b'{"detail":"Provider not available"}'

        http_error = requests.exceptions.HTTPError("400 Client Error")
        http_error.response = upstream_response
        mock_request.side_effect = http_error

        response = client.post(
            "/console/organization/create",
            json={
                "role_type": "main",
                "agent_profile": "code_supervisor",
                "provider": "claude_code",
            },
        )

        assert response.status_code == 400
        body = response.json()
        assert body["detail"] == "Provider not available"


def test_console_agent_profiles(client: TestClient) -> None:
    login(client)

    with patch(
        "cli_agent_orchestrator.control_panel.main._list_available_agent_profiles",
        return_value=["code_supervisor", "developer", "reviewer"],
    ):
        response = client.get("/console/agent-profiles")

        assert response.status_code == 200
        body = response.json()
        assert body["profiles"] == ["code_supervisor", "developer", "reviewer"]


def test_console_create_agent_profile(client: TestClient, tmp_path) -> None:
    login(client)

    with patch("cli_agent_orchestrator.control_panel.main.LOCAL_AGENT_STORE_DIR", tmp_path):
        response = client.post(
            "/console/agent-profiles",
            json={
                "name": "data_analyst",
                "description": "Analyze business data",
                "provider": "codex",
                "system_prompt": "# DATA ANALYST\nFocus on metrics.",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["profile"] == "data_analyst"

        profile_file = tmp_path / "data_analyst.md"
        assert profile_file.exists()
        content = profile_file.read_text(encoding="utf-8")
        assert "name: data_analyst" in content
        assert "description: Analyze business data" in content
        assert "provider: codex" in content
        assert "# DATA ANALYST" in content


def test_console_get_and_update_agent_profile(client: TestClient, tmp_path) -> None:
    login(client)

    profile_file = tmp_path / "designer.md"
    profile_file.write_text("---\nname: designer\ndescription: ui\n---\n\nhello\n", encoding="utf-8")

    with patch("cli_agent_orchestrator.control_panel.main.LOCAL_AGENT_STORE_DIR", tmp_path):
        get_response = client.get("/console/agent-profiles/designer")
        assert get_response.status_code == 200
        assert "description: ui" in get_response.json()["content"]

        update_response = client.put(
            "/console/agent-profiles/designer",
            json={"content": "---\nname: designer\ndescription: ui2\n---\n\nupdated\n"},
        )
        assert update_response.status_code == 200
        assert "description: ui2" in profile_file.read_text(encoding="utf-8")


def test_console_install_agent_profile(client: TestClient, tmp_path) -> None:
    login(client)

    profile_file = tmp_path / "ops.md"
    profile_file.write_text("---\nname: ops\ndescription: ops\n---\n\nrun\n", encoding="utf-8")

    with (
        patch("cli_agent_orchestrator.control_panel.main.LOCAL_AGENT_STORE_DIR", tmp_path),
        patch("cli_agent_orchestrator.control_panel.main.subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout="installed", stderr="")

        response = client.post("/console/agent-profiles/ops/install")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["return_code"] == 0
        assert "installed" in body["stdout"]
        mock_run.assert_called_once()


def test_console_agent_output_stream(client: TestClient) -> None:
    login(client)

    with patch("cli_agent_orchestrator.control_panel.main.requests.request") as mock_request:
        output_response = MagicMock()
        output_response.raise_for_status.return_value = None
        output_response.json.return_value = {"output": "stream hello"}
        mock_request.return_value = output_response

        with client.stream("GET", "/console/agents/abc123/stream?max_events=1") as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")
            body = "".join(response.iter_text())
            assert "stream hello" in body


def test_proxy_delete_request(client: TestClient) -> None:
    """Test proxying a DELETE request to cao-server."""
    login(client)

    with patch("cli_agent_orchestrator.control_panel.main.requests.request") as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_response.content = b""
        mock_response.headers = {}
        mock_request.return_value = mock_response

        response = client.delete("/sessions/test-session")

        assert response.status_code == 204
        mock_request.assert_called_once()


def test_console_tasks_success(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._get_terminals_from_sessions", return_value=[]),
        patch(
            "cli_agent_orchestrator.control_panel.main._build_organization",
            return_value={
                "leaders": [],
                "workers": [],
                "leader_groups": [
                    {
                        "leader": {"id": "leader1", "agent_profile": "code_supervisor"},
                        "members": [
                            {
                                "id": "worker1",
                                "agent_profile": "developer",
                                "status": "PROCESSING",
                                "session_name": "cao-a",
                            }
                        ],
                    }
                ],
                "unassigned_workers": [],
            },
        ),
        patch("cli_agent_orchestrator.control_panel.main._list_flow_team_links", return_value={"flowA": "leader1"}),
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._response_json_or_text") as mock_json,
    ):
        mock_request_cao.return_value = MagicMock()
        mock_json.return_value = [
            {
                "name": "flowA",
                "file_path": "examples/flow/morning-trivia.md",
                "schedule": "*/5 * * * *",
                "agent_profile": "developer",
                "provider": "kiro_cli",
                "enabled": True,
                "last_run": None,
                "next_run": None,
            }
        ]

        response = client.get("/console/tasks")

        assert response.status_code == 200
        body = response.json()
        assert len(body["teams"]) == 1
        assert body["teams"][0]["leader"]["id"] == "leader1"
        assert len(body["teams"][0]["scheduled_tasks"]) == 1
        assert body["teams"][0]["scheduled_tasks"][0]["name"] == "flowA"


def test_console_create_scheduled_task_success(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._response_json_or_text") as mock_json,
        patch("cli_agent_orchestrator.control_panel.main._set_flow_team_link") as mock_set_link,
        patch("cli_agent_orchestrator.control_panel.main._save_flow_content_to_file") as mock_save_file,
    ):
        mock_save_file.return_value = Path("/tmp/console_flows/flowA.md")
        mock_request_cao.return_value = MagicMock()
        mock_json.return_value = {
            "name": "flowA",
            "file_path": "/tmp/console_flows/flowA.md",
            "schedule": "*/5 * * * *",
            "agent_profile": "developer",
            "provider": "kiro_cli",
            "enabled": True,
        }

        response = client.post(
            "/console/tasks/scheduled",
            json={
                "flow_name": "flowA",
                "flow_content": "---\nname: flowA\nschedule: '*/5 * * * *'\nagent_profile: developer\n---\nhello",
                "leader_id": "leader1",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["flow"]["name"] == "flowA"
        assert body["saved_file_path"] == "/tmp/console_flows/flowA.md"
        mock_set_link.assert_called_once_with("flowA", "leader1")


def test_console_list_scheduled_task_files(client: TestClient, tmp_path: Path) -> None:
    login(client)

    with patch("cli_agent_orchestrator.control_panel.main.DB_DIR", tmp_path):
        flow_dir = tmp_path / "console_flows"
        flow_dir.mkdir(parents=True, exist_ok=True)
        (flow_dir / "daily.md").write_text("---\nname: daily\n---\n", encoding="utf-8")
        (flow_dir / "nightly.md").write_text("---\nname: nightly\n---\n", encoding="utf-8")

        response = client.get("/console/tasks/scheduled/files")

        assert response.status_code == 200
        body = response.json()
        names = [item["file_name"] for item in body["files"]]
        assert names == ["daily.md", "nightly.md"]


def test_console_create_scheduled_task_from_existing_file(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._resolve_console_flow_file") as mock_resolve_file,
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._response_json_or_text") as mock_json,
        patch("cli_agent_orchestrator.control_panel.main._set_flow_team_link") as mock_set_link,
    ):
        mock_resolve_file.return_value = Path("/tmp/console_flows/existing-flow.md")
        mock_request_cao.return_value = MagicMock()
        mock_json.return_value = {
            "name": "existing-flow",
            "file_path": "/tmp/console_flows/existing-flow.md",
            "schedule": "0 8 * * *",
            "agent_profile": "developer",
            "provider": "kiro_cli",
            "enabled": True,
        }

        response = client.post(
            "/console/tasks/scheduled",
            json={
                "file_name": "existing-flow.md",
                "leader_id": "leader1",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["flow"]["name"] == "existing-flow"
        mock_resolve_file.assert_called_once_with("existing-flow.md")
        mock_set_link.assert_called_once_with("existing-flow", "leader1")


def test_console_get_scheduled_task_file_content(client: TestClient, tmp_path: Path) -> None:
    login(client)

    with patch("cli_agent_orchestrator.control_panel.main.DB_DIR", tmp_path):
        flow_dir = tmp_path / "console_flows"
        flow_dir.mkdir(parents=True, exist_ok=True)
        flow_file = flow_dir / "editable.md"
        flow_file.write_text("---\nname: editable\n---\n\nhello\n", encoding="utf-8")

        response = client.get("/console/tasks/scheduled/files/editable.md")

        assert response.status_code == 200
        body = response.json()
        assert body["file_name"] == "editable.md"
        assert body["flow_name"] == "editable"
        assert "name: editable" in body["content"]


def test_console_create_scheduled_task_overwrites_selected_file_content(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._resolve_console_flow_file") as mock_resolve_file,
        patch("cli_agent_orchestrator.control_panel.main._overwrite_console_flow_file") as mock_overwrite_file,
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._response_json_or_text") as mock_json,
        patch("cli_agent_orchestrator.control_panel.main._set_flow_team_link") as mock_set_link,
    ):
        selected_path = Path("/tmp/console_flows/editable.md")
        mock_resolve_file.return_value = selected_path
        mock_overwrite_file.return_value = selected_path
        mock_request_cao.return_value = MagicMock()
        mock_json.return_value = {
            "name": "editable",
            "file_path": "/tmp/console_flows/editable.md",
            "schedule": "0 8 * * *",
            "agent_profile": "developer",
            "provider": "kiro_cli",
            "enabled": True,
        }

        response = client.post(
            "/console/tasks/scheduled",
            json={
                "file_name": "editable.md",
                "flow_content": "---\nname: editable\nschedule: '0 8 * * *'\nagent_profile: developer\n---\n\nupdated",
                "leader_id": "leader1",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        mock_resolve_file.assert_called_once_with("editable.md")
        mock_overwrite_file.assert_called_once()
        mock_set_link.assert_called_once_with("editable", "leader1")


def test_console_run_enable_disable_scheduled_task_success(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._response_json_or_text", return_value={"success": True}),
    ):
        mock_request_cao.return_value = MagicMock()

        run_resp = client.post("/console/tasks/scheduled/flowA/run")
        enable_resp = client.post("/console/tasks/scheduled/flowA/enable")
        disable_resp = client.post("/console/tasks/scheduled/flowA/disable")

        assert run_resp.status_code == 200
        assert enable_resp.status_code == 200
        assert disable_resp.status_code == 200


def test_console_delete_scheduled_task_success(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._response_json_or_text", return_value={"success": True}),
        patch("cli_agent_orchestrator.control_panel.main._remove_flow_team_link") as mock_remove_link,
    ):
        mock_request_cao.return_value = MagicMock()

        response = client.delete("/console/tasks/scheduled/flowA")

        assert response.status_code == 200
        assert response.json()["ok"] is True
        mock_remove_link.assert_called_once_with("flowA")

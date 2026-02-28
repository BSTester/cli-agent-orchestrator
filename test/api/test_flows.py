"""Tests for flow management API endpoints."""

from datetime import datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from cli_agent_orchestrator.api.main import app
from cli_agent_orchestrator.models.flow import Flow


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_list_flows_success(client: TestClient) -> None:
    with patch("cli_agent_orchestrator.api.main.flow_service.list_flows") as mock_list:
        mock_list.return_value = [
            Flow(
                name="daily-sync",
                file_path="examples/flow/morning-trivia.md",
                schedule="*/5 * * * *",
                agent_profile="developer",
                provider="kiro_cli",
                script="",
                last_run=None,
                next_run=datetime(2026, 2, 28, 10, 0, 0),
                enabled=True,
            )
        ]

        response = client.get("/flows")

        assert response.status_code == 200
        body = response.json()
        assert len(body) == 1
        assert body[0]["name"] == "daily-sync"


def test_create_flow_success(client: TestClient) -> None:
    with patch("cli_agent_orchestrator.api.main.flow_service.add_flow") as mock_add:
        mock_add.return_value = Flow(
            name="daily-sync",
            file_path="examples/flow/morning-trivia.md",
            schedule="*/5 * * * *",
            agent_profile="developer",
            provider="kiro_cli",
            script="",
            last_run=None,
            next_run=datetime(2026, 2, 28, 10, 0, 0),
            enabled=True,
        )

        response = client.post("/flows", json={"file_path": "examples/flow/morning-trivia.md"})

        assert response.status_code == 201
        assert response.json()["name"] == "daily-sync"


def test_create_flow_invalid_request(client: TestClient) -> None:
    with patch("cli_agent_orchestrator.api.main.flow_service.add_flow") as mock_add:
        mock_add.side_effect = ValueError("Invalid cron expression")

        response = client.post("/flows", json={"file_path": "bad.md"})

        assert response.status_code == 400
        assert "Invalid cron" in response.json()["detail"]


def test_run_flow_success(client: TestClient) -> None:
    with patch("cli_agent_orchestrator.api.main.flow_service.execute_flow") as mock_execute:
        mock_execute.return_value = True

        response = client.post("/flows/daily-sync/run")

        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["name"] == "daily-sync"
        assert body["executed"] is True


def test_enable_disable_and_delete_flow_success(client: TestClient) -> None:
    with (
        patch("cli_agent_orchestrator.api.main.flow_service.enable_flow") as mock_enable,
        patch("cli_agent_orchestrator.api.main.flow_service.disable_flow") as mock_disable,
        patch("cli_agent_orchestrator.api.main.flow_service.remove_flow") as mock_remove,
    ):
        enable_response = client.post("/flows/daily-sync/enable")
        disable_response = client.post("/flows/daily-sync/disable")
        delete_response = client.delete("/flows/daily-sync")

        assert enable_response.status_code == 200
        assert disable_response.status_code == 200
        assert delete_response.status_code == 200

        mock_enable.assert_called_once_with("daily-sync")
        mock_disable.assert_called_once_with("daily-sync")
        mock_remove.assert_called_once_with("daily-sync")


def test_run_flow_not_found(client: TestClient) -> None:
    with patch("cli_agent_orchestrator.api.main.flow_service.execute_flow") as mock_execute:
        mock_execute.side_effect = ValueError("Flow 'missing' not found")

        response = client.post("/flows/missing/run")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

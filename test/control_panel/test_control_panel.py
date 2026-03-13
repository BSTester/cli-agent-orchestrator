"""Tests for the control panel FastAPI interface layer."""

import json
import sqlite3
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import requests
from fastapi.testclient import TestClient

from cli_agent_orchestrator.control_panel import main as control_panel_main
from cli_agent_orchestrator.control_panel.main import CONSOLE_PASSWORD, app


@pytest.fixture
def client() -> TestClient:
    """Create a test client for the control panel app."""
    return TestClient(app)


def login(client: TestClient) -> None:
    response = client.post("/auth/login", json={"password": CONSOLE_PASSWORD})
    assert response.status_code == 200


def test_console_delete_agent_profile_success(client: TestClient, tmp_path: Path) -> None:
    login(client)

    profile_path = tmp_path / "sample_agent.md"
    profile_path.write_text("---\nname: sample_agent\n---\n\nhello", encoding="utf-8")

    process = MagicMock()
    process.returncode = 0
    process.stdout = "ok"
    process.stderr = ""

    with (
        patch("cli_agent_orchestrator.control_panel.main._validate_profile_name", return_value="sample_agent"),
        patch("cli_agent_orchestrator.control_panel.main._profile_file_path", return_value=profile_path),
        patch("cli_agent_orchestrator.control_panel.main.subprocess.run", return_value=process),
    ):
        response = client.delete("/console/agent-profiles/sample_agent")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["profile"] == "sample_agent"
    assert payload["file_deleted"] is True
    assert payload["return_code"] == 0
    assert profile_path.exists() is False


def test_console_delete_agent_profile_file_already_removed(client: TestClient, tmp_path: Path) -> None:
    login(client)

    profile_path = tmp_path / "sample_agent.md"
    profile_path.write_text("---\nname: sample_agent\n---\n\nhello", encoding="utf-8")

    process = MagicMock()
    process.returncode = 0
    process.stdout = "ok"
    process.stderr = ""

    def fake_uninstall(*_args, **_kwargs):
        if profile_path.exists():
            profile_path.unlink()
        return process

    with (
        patch("cli_agent_orchestrator.control_panel.main._validate_profile_name", return_value="sample_agent"),
        patch("cli_agent_orchestrator.control_panel.main._profile_file_path", return_value=profile_path),
        patch("cli_agent_orchestrator.control_panel.main.subprocess.run", side_effect=fake_uninstall),
    ):
        response = client.delete("/console/agent-profiles/sample_agent")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["profile"] == "sample_agent"
    assert payload["file_deleted"] is True


def test_console_delete_agent_profile_removes_display_name(client: TestClient, tmp_path: Path) -> None:
    login(client)

    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    profile_path = profile_dir / "sample_agent.md"
    profile_path.write_text("---\nname: sample_agent\n---\n\nhello", encoding="utf-8")

    db_path = tmp_path / "org.sqlite"
    process = MagicMock(returncode=0, stdout="ok", stderr="")

    with (
        patch("cli_agent_orchestrator.control_panel.main.AGENT_CONTEXT_DIR", profile_dir),
        patch("cli_agent_orchestrator.control_panel.main.DB_DIR", tmp_path),
        patch("cli_agent_orchestrator.control_panel.main.DATABASE_FILE", db_path),
        patch("cli_agent_orchestrator.control_panel.main.subprocess.run", return_value=process),
    ):
        control_panel_main._init_organization_db()
        control_panel_main._upsert_profile_display_name("sample_agent", "展示名")

        # ensure display_name stored
        with sqlite3.connect(str(db_path)) as conn:
            row = conn.execute(
                "SELECT display_name FROM agent_profile_display_names WHERE profile = ?",
                ("sample_agent",),
            ).fetchone()
        assert row and row[0] == "展示名"

        response = client.delete("/console/agent-profiles/sample_agent")

    assert response.status_code == 200
    assert response.json()["file_deleted"] is True
    assert profile_path.exists() is False

    with sqlite3.connect(str(db_path)) as conn:
        deleted_row = conn.execute(
            "SELECT display_name FROM agent_profile_display_names WHERE profile = ?",
            ("sample_agent",),
        ).fetchone()
    assert deleted_row is None


def test_console_create_agent_profile_uses_frontmatter_name(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    login(client)

    agent_dir = tmp_path / "agent-context"
    monkeypatch.setattr(control_panel_main, "AGENT_CONTEXT_DIR", agent_dir)

    content = "---\nname: cto\n---\n\nhello"
    response = client.post(
        "/console/agent-profiles",
        json={"name": "ignored_payload", "content": content, "display_name": "CTO"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile"] == "cto"
    assert Path(payload["file_path"]).name == "cto.md"
    assert (agent_dir / "cto.md").exists()


def test_console_update_agent_profile_renames_to_frontmatter_name(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    login(client)

    agent_dir = tmp_path / "agent-context"
    agent_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(control_panel_main, "AGENT_CONTEXT_DIR", agent_dir)

    original_path = agent_dir / "profile_123.md"
    original_path.write_text("---\nname: profile_123\n---\n\nold", encoding="utf-8")

    updated_content = "---\nname: cto\n---\n\nupdated"
    response = client.put(
        "/console/agent-profiles/profile_123",
        json={"content": updated_content, "display_name": "CTO"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile"] == "cto"
    new_path = agent_dir / "cto.md"
    assert Path(payload["file_path"]) == new_path
    assert new_path.exists()
    assert "updated" in new_path.read_text(encoding="utf-8")
    assert original_path.exists() is False

    list_response = client.get("/console/agent-profiles/files")
    assert list_response.status_code == 200
    files = list_response.json()["files"]
    assert any(
        item.get("file_name") == "cto.md" and item.get("display_name") == "CTO" for item in files
    )


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


def test_static_ui_served_without_auth(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")


def test_auth_required_for_proxy_routes(client: TestClient) -> None:
    response = client.get("/api/sessions")
    assert response.status_code == 401


def test_console_provider_config_summary(client: TestClient) -> None:
    login(client)

    summary = {
        "should_show_guide": True,
        "onboarding": {"dismissed": False, "dismissed_at": None, "completed_at": None},
        "providers": [
            {
                "id": "claude_code",
                "label": "Claude Code",
                "command": "claude",
                "supports_account_login": True,
                "supports_api_config": True,
                "default_selected": True,
                "status": {"installed": True, "configured": False},
                "saved_settings": {},
            }
        ],
    }

    with patch(
        "cli_agent_orchestrator.control_panel.main._build_provider_guide_summary",
        return_value=summary,
    ):
        response = client.get("/console/provider-config/summary")

    assert response.status_code == 200
    assert response.json() == summary


def test_console_provider_config_single_provider(client: TestClient) -> None:
    login(client)

    provider = {
        "id": "claude_code",
        "label": "Claude Code",
        "command": "claude",
        "supports_account_login": True,
        "supports_api_config": True,
        "default_selected": True,
        "login_command": "claude login",
        "logout_command": None,
        "login_supported": True,
        "logout_supported": False,
        "status": {"installed": True, "configured": False},
        "saved_settings": {},
    }

    with patch(
        "cli_agent_orchestrator.control_panel.main._build_single_provider_guide",
        return_value=provider,
    ):
        response = client.get("/console/provider-config/providers/claude_code")

    assert response.status_code == 200
    assert response.json() == provider


def test_build_provider_action_metadata_hides_unsupported_logout() -> None:
    item = {
        "id": "claude_code",
        "label": "Claude Code",
        "command": "claude",
        "supports_account_login": True,
        "supports_api_config": True,
        "default_selected": True,
        "login_command": "claude login",
        "logout_command": "claude logout",
    }

    with patch(
        "cli_agent_orchestrator.control_panel.main._probe_cli_subcommand",
        return_value=False,
    ):
        payload = control_panel_main._build_provider_action_metadata(item)

    assert payload == {
        "console_command": None,
        "login_command": "claude login",
        "logout_command": None,
        "login_via_console": False,
        "logout_via_console": False,
        "login_supported": True,
        "logout_supported": False,
    }


def test_build_provider_action_metadata_supports_console_slash_flow() -> None:
    item = {
        "id": "qoder_cli",
        "label": "QoderCLI",
        "command": "qodercli",
        "supports_account_login": True,
        "supports_api_config": False,
        "default_selected": True,
        "console_command": "qodercli",
        "login_command": "/login",
        "logout_command": "/logout",
        "login_via_console": True,
        "logout_via_console": True,
    }

    payload = control_panel_main._build_provider_action_metadata(item)

    assert payload == {
        "console_command": "qodercli",
        "login_command": "/login",
        "logout_command": "/logout",
        "login_via_console": True,
        "logout_via_console": True,
        "login_supported": True,
        "logout_supported": True,
    }


def test_build_provider_action_metadata_uses_kiro_device_flow_login() -> None:
    item = {
        "id": "kiro_cli",
        "label": "Kiro CLI",
        "command": "kiro-cli",
        "supports_account_login": True,
        "supports_api_config": False,
        "default_selected": True,
        "login_command": "kiro-cli login --use-device-flow",
        "logout_command": "kiro-cli logout",
    }

    with patch(
        "cli_agent_orchestrator.control_panel.main._probe_cli_subcommand",
        return_value=True,
    ):
        payload = control_panel_main._build_provider_action_metadata(item)

    assert payload == {
        "console_command": None,
        "login_command": "kiro-cli login --use-device-flow",
        "logout_command": "kiro-cli logout",
        "login_via_console": False,
        "logout_via_console": False,
        "login_supported": True,
        "logout_supported": True,
    }


def test_detect_codex_status_marks_api_key_login_as_configured() -> None:
        process = MagicMock(returncode=0, stdout="Logged in using an API key - demo***1234", stderr="")

        with (
                patch("cli_agent_orchestrator.control_panel.main.shutil.which", return_value="/usr/bin/codex"),
                patch("cli_agent_orchestrator.control_panel.main._run_provider_command", return_value=process),
                patch("cli_agent_orchestrator.control_panel.main._get_provider_saved_settings", return_value={}),
        ):
                payload = control_panel_main._detect_codex_status()

        assert payload["installed"] is True
        assert payload["configured"] is True
        assert payload["detected_mode"] == "api"


def test_detect_claude_status_prefers_api_saved_settings() -> None:
        process = MagicMock(
                stdout='{"loggedIn": true, "authMethod": "oauth_token", "apiProvider": "firstParty"}',
                stderr="",
        )
        saved_settings = {
                "mode": "api",
                "api_base_url": "https://example.invalid/anthropic",
                "api_key": "secret-key",
                "default_model": "claude-sonnet-4-5",
        }

        with (
                patch("cli_agent_orchestrator.control_panel.main.shutil.which", return_value="/usr/bin/claude"),
                patch("cli_agent_orchestrator.control_panel.main._run_provider_command", return_value=process),
                patch(
                        "cli_agent_orchestrator.control_panel.main._get_provider_saved_settings",
                        return_value=saved_settings,
                ),
        ):
                payload = control_panel_main._detect_claude_status()

        assert payload["configured"] is True
        assert payload["detected_mode"] == "api"
        assert payload["details"] == "claude-sonnet-4-5"


def test_detect_claude_status_missing_settings_file_treated_as_unconfigured(tmp_path: Path) -> None:
    missing_path = tmp_path / "settings.json"

    with (
        patch("cli_agent_orchestrator.control_panel.main.shutil.which", return_value="/usr/bin/claude"),
        patch(
            "cli_agent_orchestrator.control_panel.main._provider_settings_path",
            return_value=missing_path,
        ),
        patch("cli_agent_orchestrator.control_panel.main._run_provider_command") as run_mock,
        patch("cli_agent_orchestrator.control_panel.main._get_provider_saved_settings") as saved_mock,
    ):
        payload = control_panel_main._detect_claude_status()

    run_mock.assert_not_called()
    saved_mock.assert_not_called()
    assert payload["installed"] is True
    assert payload["configured"] is False
    assert payload["detected_mode"] is None
    assert payload["details"] == ""
    assert payload["settings_path"] == str(missing_path)


def test_detect_codebuddy_status_timeout_treated_as_unconfigured() -> None:
        with (
            patch("cli_agent_orchestrator.control_panel.main.shutil.which", return_value="/usr/bin/codebuddy"),
            patch("cli_agent_orchestrator.control_panel.main.get_provider_runtime_settings", return_value={}),
            patch(
                "cli_agent_orchestrator.control_panel.main._run_provider_command",
                side_effect=subprocess.TimeoutExpired(
                    cmd=["codebuddy", "config", "get", "model"],
                    timeout=25,
                ),
            ),
        ):
            payload = control_panel_main._detect_codebuddy_status()

        assert payload["installed"] is True
        assert payload["configured"] is False
        assert payload["detected_mode"] is None
        assert payload["details"] == ""


def test_console_provider_config_summary_treats_codebuddy_timeout_as_unconfigured(
    client: TestClient,
) -> None:
        login(client)

        with (
            patch(
                "cli_agent_orchestrator.control_panel.main.CONTROL_PANEL_PROVIDER_GUIDES",
                [
                    {
                        "id": "codebuddy",
                        "label": "CodeBuddy",
                        "command": "codebuddy",
                        "supports_account_login": True,
                        "supports_api_config": False,
                        "default_selected": True,
                        "console_command": "codebuddy",
                        "login_command": "/login",
                        "logout_command": "/logout",
                        "login_via_console": True,
                        "logout_via_console": True,
                    }
                ],
            ),
            patch("cli_agent_orchestrator.control_panel.main.shutil.which", return_value="/usr/bin/codebuddy"),
            patch("cli_agent_orchestrator.control_panel.main.get_provider_runtime_settings", return_value={}),
            patch(
                "cli_agent_orchestrator.control_panel.main.load_provider_runtime_config",
                return_value={
                    "version": 1,
                    "onboarding": {
                        "dismissed": False,
                        "dismissed_at": None,
                        "completed_at": None,
                    },
                    "providers": {},
                },
            ),
            patch(
                "cli_agent_orchestrator.control_panel.main._run_provider_command",
                side_effect=subprocess.TimeoutExpired(
                    cmd=["codebuddy", "config", "get", "model"],
                    timeout=25,
                ),
            ),
        ):
            response = client.get("/console/provider-config/summary")

        assert response.status_code == 200
        payload = response.json()
        assert payload["should_show_guide"] is True
        assert len(payload["providers"]) == 1
        assert payload["providers"][0]["id"] == "codebuddy"
        assert payload["providers"][0]["status"]["installed"] is True
        assert payload["providers"][0]["status"]["configured"] is False


def test_console_provider_config_summary_skips_missing_config_file(client: TestClient, tmp_path: Path) -> None:
        login(client)
        missing_path = tmp_path / "settings.json"

        with (
            patch(
                "cli_agent_orchestrator.control_panel.main.CONTROL_PANEL_PROVIDER_GUIDES",
                [
                    {
                        "id": "claude_code",
                        "label": "Claude Code",
                        "command": "claude",
                        "supports_account_login": True,
                        "supports_api_config": True,
                        "default_selected": True,
                    }
                ],
            ),
            patch("cli_agent_orchestrator.control_panel.main.shutil.which", return_value="/usr/bin/claude"),
            patch(
                "cli_agent_orchestrator.control_panel.main._provider_settings_path",
                return_value=missing_path,
            ),
            patch(
                "cli_agent_orchestrator.control_panel.main.load_provider_runtime_config",
                return_value={
                    "version": 1,
                    "onboarding": {
                        "dismissed": False,
                        "dismissed_at": None,
                        "completed_at": None,
                    },
                    "providers": {
                        "claude_code": {
                            "mode": "api",
                            "api_key": "secret-key",
                            "default_model": "claude-sonnet-4-5",
                        }
                    },
                },
            ),
            patch("cli_agent_orchestrator.control_panel.main._run_provider_command") as run_mock,
        ):
            response = client.get("/console/provider-config/summary")

        run_mock.assert_not_called()
        assert response.status_code == 200
        payload = response.json()
        assert payload["should_show_guide"] is True
        assert len(payload["providers"]) == 1
        assert payload["providers"][0]["id"] == "claude_code"
        assert payload["providers"][0]["status"]["configured"] is False
        assert payload["providers"][0]["status"]["settings_path"] == str(missing_path)
        assert payload["providers"][0]["saved_settings"] == {}


def test_read_openclaw_saved_settings_maps_existing_config(tmp_path: Path) -> None:
        config_path = tmp_path / "openclaw.json"
        config_path.write_text(
                """
{
    "auth": {
        "profiles": {
            "zai:default": {
                "provider": "zai",
                "mode": "api_key"
            }
        }
    },
    "models": {
        "providers": {
            "zai": {
                "baseUrl": "https://open.bigmodel.cn/api/coding/paas/v4",
                "api": "openai-completions"
            }
        }
    },
    "agents": {
        "defaults": {
            "model": {
                "primary": "zai/glm-4.7"
            }
        }
    },
    "channels": {
        "feishu": {
            "enabled": true,
            "domain": "feishu",
            "connectionMode": "webhook",
            "verificationToken": "verify-token",
            "defaultAccount": "main",
            "accounts": {
                "main": {
                    "appId": "cli_xxx",
                    "appSecret": "secret-yyy",
                    "botName": "bot"
                }
            }
        }
    }
}
                """.strip(),
                encoding="utf-8",
        )

        with patch(
                "cli_agent_orchestrator.control_panel.main._provider_settings_path",
                return_value=config_path,
        ):
                payload = control_panel_main._read_openclaw_saved_settings()

        assert payload["mode"] == "api"
        assert payload["api_base_url"] == "https://open.bigmodel.cn/api/coding/paas/v4"
        assert payload["default_model"] == "glm-4.7"
        assert payload["compatibility"] == "openai"
        assert payload["feishu"] == {
                "enabled": True,
                "domain": "feishu",
                "connection_mode": "webhook",
                "app_id": "cli_xxx",
                "app_secret": "secret-yyy",
                "bot_name": "bot",
                "verification_token": "verify-token",
                "dm_policy": "pairing",
                "account_id": "main",
        }


        def test_read_codex_saved_settings_reads_auth_json_api_key(tmp_path: Path) -> None:
            codex_dir = tmp_path / ".codex"
            codex_dir.mkdir()
            config_path = codex_dir / "config.toml"
            config_path.write_text(
                """
        model = "gpt-5-codex"
        model_provider = "openai"

        [model_providers.openai]
        base_url = "https://api.openai.com/v1"
        api_key_env = "OPENAI_API_KEY"
                """.strip(),
                encoding="utf-8",
            )
            auth_path = codex_dir / "auth.json"
            auth_path.write_text(
                json.dumps(
                    {
                        "auth_mode": "apikey",
                        "OPENAI_API_KEY": "auth-json-secret",
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch("cli_agent_orchestrator.control_panel.main._provider_settings_path", return_value=config_path),
                patch("cli_agent_orchestrator.control_panel.main.Path.home", return_value=tmp_path),
                patch.dict("cli_agent_orchestrator.control_panel.main.os.environ", {}, clear=True),
            ):
                payload = control_panel_main._read_codex_saved_settings()

            assert payload == {
                "mode": "api",
                "api_base_url": "https://api.openai.com/v1",
                "default_model": "gpt-5-codex",
                "api_key": "auth-json-secret",
            }


def test_read_codex_saved_settings_reads_auth_json_env_api_key(tmp_path: Path) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    config_path = codex_dir / "config.toml"
    config_path.write_text(
        """
model = "gpt-5-codex"
model_provider = "api"

[model_providers.api]
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"
        """.strip(),
        encoding="utf-8",
    )
    auth_path = codex_dir / "auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "auth_mode": "apikey",
                "ENV": {
                    "OPENAI_API_KEY": "env-secret",
                },
            }
        ),
        encoding="utf-8",
    )

    with (
        patch("cli_agent_orchestrator.control_panel.main._provider_settings_path", return_value=config_path),
        patch("cli_agent_orchestrator.control_panel.main.Path.home", return_value=tmp_path),
        patch.dict("cli_agent_orchestrator.control_panel.main.os.environ", {}, clear=True),
    ):
        payload = control_panel_main._read_codex_saved_settings()

    assert payload == {
        "mode": "api",
        "api_base_url": "https://api.openai.com/v1",
        "default_model": "gpt-5-codex",
        "api_key": "env-secret",
    }


def test_write_claude_settings_keeps_single_api_key(tmp_path: Path) -> None:
    with patch("cli_agent_orchestrator.control_panel.main.Path.home", return_value=tmp_path):
        settings_path = control_panel_main._write_claude_settings(
            "https://api.anthropic.test",
            "secret-key",
            "claude-sonnet-4-6",
        )

    payload = json.loads(settings_path.read_text(encoding="utf-8"))
    env_payload = payload["env"]
    assert env_payload["ANTHROPIC_BASE_URL"] == "https://api.anthropic.test"
    assert env_payload["ANTHROPIC_API_KEY"] == "secret-key"
    assert env_payload["ANTHROPIC_MODEL"] == "claude-sonnet-4-6"
    assert "ANTHROPIC_AUTH_TOKEN" not in env_payload
    assert "ANTHROPIC_API_TOKEN" not in env_payload


def test_write_codex_config_uses_openai_api_key_env(tmp_path: Path) -> None:
    with patch("cli_agent_orchestrator.control_panel.main.Path.home", return_value=tmp_path):
        config_path = control_panel_main._write_codex_config("gpt-5-codex", "https://api.openai.com/v1")

    config_content = config_path.read_text(encoding="utf-8")
    assert 'api_key_env = "OPENAI_API_KEY"' in config_content
    assert 'base_url = "https://api.openai.com/v1"' in config_content
    assert 'model = "gpt-5-codex"' in config_content


def test_write_codex_auth_writes_openai_api_key_at_top_level(tmp_path: Path) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    auth_path = codex_dir / "auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "API_KEY": "stale-key",
                "OPENROUTER_API_KEY": "keep-me",
                "ENV": {
                    "API_KEY": "stale-key",
                },
            }
        ),
        encoding="utf-8",
    )

    with patch("cli_agent_orchestrator.control_panel.main.Path.home", return_value=tmp_path):
        saved_path = control_panel_main._write_codex_auth("new-secret")

    payload = json.loads(saved_path.read_text(encoding="utf-8"))
    assert payload["auth_mode"] == "apikey"
    assert payload["OPENAI_API_KEY"] == "new-secret"
    assert payload["OPENROUTER_API_KEY"] == "keep-me"
    assert "API_KEY" not in payload
    assert "ENV" not in payload


def test_write_codex_auth_preserves_unrelated_env_entries(tmp_path: Path) -> None:
    codex_dir = tmp_path / ".codex"
    codex_dir.mkdir()
    auth_path = codex_dir / "auth.json"
    auth_path.write_text(
        json.dumps(
            {
                "ENV": {
                    "CUSTOM_FLAG": "keep-me",
                    "OPENAI_API_KEY": "stale-key",
                    "API_KEY": "stale-key",
                },
            }
        ),
        encoding="utf-8",
    )

    with patch("cli_agent_orchestrator.control_panel.main.Path.home", return_value=tmp_path):
        saved_path = control_panel_main._write_codex_auth("new-secret")

    payload = json.loads(saved_path.read_text(encoding="utf-8"))
    assert payload["OPENAI_API_KEY"] == "new-secret"
    assert payload["ENV"] == {"CUSTOM_FLAG": "keep-me"}


def test_save_provider_config_file_openclaw_restarts_gateway(tmp_path: Path) -> None:
    config_path = tmp_path / "openclaw.json"

    with (
        patch("cli_agent_orchestrator.control_panel.main._provider_settings_path", return_value=config_path),
        patch(
            "cli_agent_orchestrator.control_panel.main._restart_openclaw_gateway",
            return_value={"command": "openclaw gateway restart", "stdout": "ok", "stderr": ""},
        ),
    ):
        payload = control_panel_main._save_provider_config_file(
            "openclaw",
            '{"channels":{"feishu":{"enabled":true}}}',
        )

    assert payload == {
        "provider_id": "openclaw",
        "path": str(config_path),
        "content": '{\n  "channels": {\n    "feishu": {\n      "enabled": true\n    }\n  }\n}\n',
        "gateway": {"command": "openclaw gateway restart", "stdout": "ok", "stderr": ""},
    }
    assert config_path.read_text(encoding="utf-8") == payload["content"]


def test_console_provider_config_onboarding(client: TestClient) -> None:
    login(client)

    onboarding = {
        "dismissed": True,
        "dismissed_at": "2025-01-01T00:00:00+00:00",
        "completed_at": None,
    }

    with patch(
        "cli_agent_orchestrator.control_panel.main.set_onboarding_state",
        return_value=onboarding,
    ) as mock_set_onboarding:
        response = client.post("/console/provider-config/onboarding", json={"dismissed": True})

    assert response.status_code == 200
    assert response.json() == {"ok": True, "onboarding": onboarding}
    mock_set_onboarding.assert_called_once_with(dismissed=True)


def test_console_provider_config_apply_claude_api(client: TestClient, tmp_path: Path) -> None:
    login(client)

    settings_path = tmp_path / "settings.json"
    runtime_settings = {
        "mode": "api",
        "api_base_url": "https://example.invalid/v1",
        "default_model": "claude-sonnet-4-6",
        "updated_at": "2025-01-01T00:00:00+00:00",
    }
    onboarding = {
        "dismissed": True,
        "dismissed_at": "2025-01-01T00:00:00+00:00",
        "completed_at": "2025-01-01T00:00:00+00:00",
    }

    with (
        patch(
            "cli_agent_orchestrator.control_panel.main._write_claude_settings",
            return_value=settings_path,
        ) as mock_write_settings,
        patch(
            "cli_agent_orchestrator.control_panel.main.update_provider_runtime_settings",
            return_value=runtime_settings,
        ) as mock_update_runtime,
        patch(
            "cli_agent_orchestrator.control_panel.main.set_onboarding_state",
            return_value=onboarding,
        ) as mock_set_onboarding,
    ):
        response = client.post(
            "/console/provider-config/apply",
            json={
                "provider_id": "claude_code",
                "mode": "api",
                "api_base_url": "https://example.invalid/v1",
                "api_key": "secret-key",
                "default_model": "claude-sonnet-4-6",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["provider_id"] == "claude_code"
    assert payload["saved_path"] == str(settings_path)
    assert payload["settings"] == {
        "mode": "api",
        "api_base_url": "https://example.invalid/v1",
        "default_model": "claude-sonnet-4-6",
        "updated_at": "2025-01-01T00:00:00+00:00",
    }
    mock_write_settings.assert_called_once_with(
        "https://example.invalid/v1", "secret-key", "claude-sonnet-4-6"
    )
    mock_update_runtime.assert_called_once_with(
        "claude_code",
        {
            "mode": "api",
            "api_base_url": "https://example.invalid/v1",
            "api_key": "secret-key",
            "default_model": "claude-sonnet-4-6",
            "compatibility": None,
        },
    )
    mock_set_onboarding.assert_called_once_with(completed=True)


def test_console_provider_config_apply_codex_api(client: TestClient, tmp_path: Path) -> None:
    login(client)

    config_path = tmp_path / "config.toml"
    auth_path = tmp_path / "auth.json"
    runtime_settings = {
        "mode": "api",
        "api_base_url": "https://api.openai.com/v1",
        "default_model": "gpt-5-codex",
        "updated_at": "2025-01-01T00:00:00+00:00",
    }
    onboarding = {
        "dismissed": True,
        "dismissed_at": "2025-01-01T00:00:00+00:00",
        "completed_at": "2025-01-01T00:00:00+00:00",
    }

    with (
        patch(
            "cli_agent_orchestrator.control_panel.main._write_codex_config",
            return_value=config_path,
        ) as mock_write_config,
        patch(
            "cli_agent_orchestrator.control_panel.main._write_codex_auth",
            return_value=auth_path,
        ) as mock_write_auth,
        patch(
            "cli_agent_orchestrator.control_panel.main.update_provider_runtime_settings",
            return_value=runtime_settings,
        ) as mock_update_runtime,
        patch(
            "cli_agent_orchestrator.control_panel.main.set_onboarding_state",
            return_value=onboarding,
        ) as mock_set_onboarding,
    ):
        response = client.post(
            "/console/provider-config/apply",
            json={
                "provider_id": "codex",
                "mode": "api",
                "api_base_url": "https://api.openai.com/v1",
                "api_key": "secret-key",
                "default_model": "gpt-5-codex",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["provider_id"] == "codex"
    assert payload["saved_path"] == str(config_path)
    mock_write_config.assert_called_once_with("gpt-5-codex", "https://api.openai.com/v1")
    mock_write_auth.assert_called_once_with("secret-key")
    mock_update_runtime.assert_called_once_with(
        "codex",
        {
            "mode": "api",
            "api_base_url": "https://api.openai.com/v1",
            "api_key": "secret-key",
            "default_model": "gpt-5-codex",
            "compatibility": None,
        },
    )
    mock_set_onboarding.assert_called_once_with(completed=True)


def test_console_provider_config_kiro_callback_rejects_non_localhost(client: TestClient) -> None:
    login(client)

    response = client.post(
        "/console/provider-config/kiro/callback",
        json={"callback_url": "https://example.com/callback"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "callback_url must target localhost or 127.0.0.1"


def test_console_provider_config_kiro_callback_success(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main.requests.get") as mock_get,
        patch("cli_agent_orchestrator.control_panel.main.update_provider_runtime_settings") as mock_update_runtime,
        patch("cli_agent_orchestrator.control_panel.main.set_onboarding_state") as mock_set_onboarding,
    ):
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.text = "ok"
        mock_get.return_value = mock_response

        response = client.post(
            "/console/provider-config/kiro/callback",
            json={"callback_url": "http://localhost:49153/callback?code=abc"},
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "status_code": 200, "body": "ok"}
    mock_get.assert_called_once_with("http://localhost:49153/callback?code=abc", timeout=20)
    mock_update_runtime.assert_called_once()
    mock_set_onboarding.assert_called_once_with(completed=True)


def test_console_provider_config_file_read(client: TestClient) -> None:
    login(client)

    payload = {
        "provider_id": "openclaw",
        "path": "/tmp/openclaw.json",
        "content": "{}\n",
    }

    with patch(
        "cli_agent_orchestrator.control_panel.main._read_provider_config_file",
        return_value=payload,
    ) as mock_read_file:
        response = client.get("/console/provider-config/openclaw/file")

    assert response.status_code == 200
    assert response.json() == payload
    mock_read_file.assert_called_once_with("openclaw")


def test_console_provider_config_file_save(client: TestClient) -> None:
    login(client)

    payload = {
        "provider_id": "openclaw",
        "path": "/tmp/openclaw.json",
        "content": "{\n  \"foo\": true\n}\n",
        "gateway": {"command": "openclaw gateway restart", "stdout": "ok", "stderr": ""},
    }

    with patch(
        "cli_agent_orchestrator.control_panel.main._save_provider_config_file",
        return_value=payload,
    ) as mock_save_file:
        response = client.put(
            "/console/provider-config/openclaw/file",
            json={"content": '{"foo":true}'},
        )

    assert response.status_code == 200
    assert response.json() == payload
    mock_save_file.assert_called_once_with("openclaw", '{"foo":true}')


def test_proxy_get_request(client: TestClient) -> None:
    """Test proxying a GET request to cao-server."""
    login(client)

    with patch("cli_agent_orchestrator.control_panel.main.requests.request") as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b'{"result": "success"}'
        mock_response.headers = {"Content-Type": "application/json"}
        mock_request.return_value = mock_response

        response = client.get("/api/sessions")

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

        response = client.post("/api/sessions", json={"agent_profile": "test", "provider": "kiro_cli"})

        assert response.status_code == 201
        mock_request.assert_called_once()


def test_proxy_handles_cao_server_error(client: TestClient) -> None:
    """Test proxy handles cao-server connection errors."""
    login(client)

    with patch("cli_agent_orchestrator.control_panel.main.requests.request") as mock_request:
        mock_request.side_effect = requests.exceptions.ConnectionError("Connection failed")

        response = client.get("/api/sessions")

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

        client.get("/api/sessions?limit=10&offset=20")

        call_args = mock_request.call_args
        assert "limit=10" in call_args.kwargs["url"]
        assert "offset=20" in call_args.kwargs["url"]


def test_console_overview(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main.requests.request") as mock_request,
        patch(
            "cli_agent_orchestrator.control_panel.main.console_tasks",
            new_callable=AsyncMock,
        ) as mock_console_tasks,
    ):
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
        mock_console_tasks.return_value = {
            "teams": [
                {
                    "leader": {"id": "leader-1"},
                    "team_alias": "team-alpha",
                    "members": [],
                    "instant_tasks": [],
                    "scheduled_tasks": [],
                }
            ],
            "unassigned_scheduled_tasks": [],
        }

        response = client.get("/console/overview")

        assert response.status_code == 200
        data = response.json()
        assert data["agents_total"] == 1
        assert data["main_agents_total"] == 1
        assert data["provider_counts"]["kiro_cli"] == 1
        assert data["teams"][0]["leader"]["id"] == "leader-1"
        assert data["team_leaders"][0]["id"] == "leader-1"


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


def test_console_ws_token_creation(client: TestClient) -> None:
    login(client)

    response = client.post("/console/ws-token")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("token"), str)
    assert len(body["token"]) > 10
    assert isinstance(body.get("expires_in"), int)
    assert body["expires_in"] > 0


def test_console_create_shell_terminal_success(client: TestClient) -> None:
    login(client)

    fake_terminal = MagicMock(
        id="shell1234",
        session_name="cao-shell-session",
        provider="shell",
    )

    with (
        patch(
            "cli_agent_orchestrator.control_panel.main.terminal_service.create_shell_terminal",
            return_value=fake_terminal,
        ) as mock_create,
        patch(
            "cli_agent_orchestrator.control_panel.main.terminal_service.get_working_directory",
            return_value="/home/penn/workspace",
        ) as mock_get_workdir,
    ):
        response = client.post("/console/terminals/shell", json={})

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "terminal_id": "shell1234",
        "session_name": "cao-shell-session",
        "provider": "shell",
        "working_directory": "/home/penn/workspace",
    }
    mock_create.assert_called_once_with(None, None)
    mock_get_workdir.assert_called_once_with("shell1234")


def test_console_agent_tmux_input_and_output(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main.requests.request") as mock_request,
        patch("cli_agent_orchestrator.control_panel.main.tmux_client") as mock_tmux,
    ):
        terminal_detail = MagicMock()
        terminal_detail.raise_for_status.return_value = None
        terminal_detail.json.return_value = {
            "id": "abc123",
            "tmux_session": "cao-test",
            "tmux_window": "worker-1",
        }
        mock_request.return_value = terminal_detail
        mock_tmux.get_history.return_value = "hello from tmux"

        send_resp = client.post(
            "/console/agents/abc123/tmux/input",
            json={"message": "ls -la", "press_enter": True},
        )
        assert send_resp.status_code == 200
        send_body = send_resp.json()
        assert send_body["ok"] is True
        mock_tmux.send_raw_input.assert_called_once_with("cao-test", "worker-1", "ls -la")
        mock_tmux.send_special_key.assert_called_once_with("cao-test", "worker-1", "C-m")

        output_resp = client.get("/console/agents/abc123/tmux/output?lines=222")
        assert output_resp.status_code == 200
        output_body = output_resp.json()
        assert output_body["output"] == "hello from tmux"
        assert output_body["lines"] == 222


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


def test_console_create_main_team_with_new_working_directory(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._resolve_home_level1_directory", return_value="/home/test/team-alpha") as mock_resolve_workdir,
        patch("cli_agent_orchestrator.control_panel.main._register_team") as mock_register_team,
        patch("cli_agent_orchestrator.control_panel.main._set_team_working_directory") as mock_set_team_workdir,
        patch("cli_agent_orchestrator.control_panel.main.requests.request") as mock_request,
    ):
        created = MagicMock()
        created.raise_for_status.return_value = None
        created.json.return_value = {
            "id": "leader-main-2",
            "agent_profile": "code_supervisor",
            "session_name": "cao-main-2",
        }
        mock_request.return_value = created

        response = client.post(
            "/console/organization/create",
            json={
                "role_type": "main",
                "agent_profile": "code_supervisor",
                "team_workdir_mode": "new",
                "team_workdir_name": "team-alpha",
            },
        )

        assert response.status_code == 200
        assert response.json()["ok"] is True
        mock_resolve_workdir.assert_called_once_with(
            "team-alpha",
            must_exist=True,
            create_if_missing=True,
        )
        mock_register_team.assert_called_once_with("leader-main-2")
        mock_set_team_workdir.assert_called_once_with("leader-main-2", "/home/test/team-alpha")

        create_call = mock_request.call_args
        assert create_call.kwargs["params"]["working_directory"] == "/home/test/team-alpha"


def test_console_create_org_worker_inherits_team_working_directory(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._list_team_working_directories", return_value={"leader1": "/home/test/team-alpha"}),
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
            "working_directory": "/home/test/team-alpha",
        }

        created = MagicMock()
        created.raise_for_status.return_value = None
        created.json.return_value = {
            "id": "worker9",
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
        assert response.json()["ok"] is True
        mock_register_team.assert_called_once_with("leader1")
        mock_set_worker_link.assert_called_once_with("worker9", "leader1")

        create_call = mock_request.call_args_list[1]
        assert create_call.kwargs["params"]["working_directory"] == "/home/test/team-alpha"


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


def test_console_create_org_worker_defaults_agent_alias_from_profile_display_name(
    client: TestClient,
) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._register_team") as mock_register_team,
        patch("cli_agent_orchestrator.control_panel.main._set_worker_link") as mock_set_worker_link,
        patch("cli_agent_orchestrator.control_panel.main._set_agent_alias") as mock_set_agent_alias,
        patch(
            "cli_agent_orchestrator.control_panel.main._resolve_available_profile_display_name",
            return_value="后端工程师",
        ),
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
        mock_register_team.assert_called_once_with("leader1")
        mock_set_worker_link.assert_called_once_with("worker1", "leader1")
        mock_set_agent_alias.assert_called_once_with("worker1", "后端工程师")


def test_console_auto_set_agent_alias_uses_available_profile_display_name(
    client: TestClient,
) -> None:
    with (
        patch(
            "cli_agent_orchestrator.control_panel.main._resolve_available_profile_display_name",
            return_value="工程师",
        ),
        patch("cli_agent_orchestrator.control_panel.main._set_agent_alias") as mock_set_agent_alias,
    ):
        response = client.post(
            "/console/internal/agent-alias/auto-set",
            json={"terminal_id": "worker-1", "agent_profile": "developer"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "ok": True,
            "terminal_id": "worker-1",
            "agent_alias": "工程师",
        }
        mock_set_agent_alias.assert_called_once_with("worker-1", "工程师")


def test_console_internal_organization_link_is_accessible_without_login(
    client: TestClient,
) -> None:
    with (
        patch("cli_agent_orchestrator.control_panel.main._register_team") as mock_register_team,
        patch("cli_agent_orchestrator.control_panel.main._set_worker_link") as mock_set_worker_link,
        patch("cli_agent_orchestrator.control_panel.main.requests.request") as mock_request,
    ):
        worker = MagicMock()
        worker.raise_for_status.return_value = None
        worker.json.return_value = {
            "id": "worker1",
            "agent_profile": "developer",
            "session_name": "cao-team1",
        }

        leader = MagicMock()
        leader.raise_for_status.return_value = None
        leader.json.return_value = {
            "id": "leader1",
            "agent_profile": "code_supervisor",
            "session_name": "cao-team1",
        }

        mock_request.side_effect = [worker, leader]

        response = client.post(
            "/console/internal/organization/link",
            json={"worker_id": "worker1", "leader_id": "leader1"},
        )

        assert response.status_code == 200
        assert response.json() == {"ok": True, "worker_id": "worker1", "leader_id": "leader1"}
        mock_register_team.assert_called_once_with("leader1")
        mock_set_worker_link.assert_called_once_with("worker1", "leader1")


def test_console_home_workdirs_lists_home_level1_directories(client: TestClient, tmp_path: Path) -> None:
    login(client)

    (tmp_path / "team-a").mkdir()
    (tmp_path / "team-b").mkdir()
    (tmp_path / "not-a-dir.txt").write_text("x", encoding="utf-8")

    with patch("cli_agent_orchestrator.control_panel.main._home_directory", return_value=tmp_path.resolve()):
        response = client.get("/console/workdirs/home")

    assert response.status_code == 200
    body = response.json()
    assert body["home_directory"] == str(tmp_path.resolve())
    names = [item["name"] for item in body["directories"]]
    assert names == ["team-a", "team-b"]


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


@pytest.mark.asyncio
async def test_restart_team_leader_task_restarts_terminal_and_rekeys() -> None:
    with (
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._response_json_or_text") as mock_json,
        patch(
            "cli_agent_orchestrator.control_panel.main._get_team_runtime",
            return_value={
                "leader_id": "leader1",
                "terminal_id": "leader1",
                "session_name": "cao-team1",
                "provider": "kiro_cli",
                "agent_profile": "code_supervisor",
                "working_directory": "/home/penn/workspace/team-a",
            },
        ),
        patch(
            "cli_agent_orchestrator.control_panel.main._list_team_working_directories",
            return_value={"leader1": "/home/penn/workspace/team-a"},
        ),
        patch("cli_agent_orchestrator.control_panel.main._list_live_sessions", return_value={"cao-team1"}),
        patch("cli_agent_orchestrator.control_panel.main._rekey_leader_id") as mock_rekey,
        patch("cli_agent_orchestrator.control_panel.main._set_team_alias") as mock_set_team_alias,
        patch("cli_agent_orchestrator.control_panel.main._set_team_working_directory") as mock_set_team_workdir,
        patch("cli_agent_orchestrator.control_panel.main._upsert_team_runtime") as mock_runtime,
    ):
        mock_request_cao.side_effect = [MagicMock(), MagicMock(), MagicMock()]
        mock_json.side_effect = [
            {
                "id": "leader1",
                "session_name": "cao-team1",
                "provider": "kiro_cli",
                "agent_profile": "code_supervisor",
            },
            {
                "id": "leader2",
                "session_name": "cao-team1",
                "provider": "codex",
                "agent_profile": "reviewer",
            },
        ]

        payload = control_panel_main.OrgLeaderUpdateRequest(
            agent_profile="reviewer",
            provider="codex",
            team_alias="新团队",
            team_workdir_mode="existing",
            team_workdir_name="team-a",
        )
        result = await control_panel_main._restart_team_leader_task(
            normalized_leader_id="leader1",
            payload=payload,
            requested_working_directory="/home/penn/workspace/team-a",
        )

        assert result["ok"] is True
        assert result["leader_id"] == "leader2"
        assert result["previous_leader_id"] == "leader1"
        mock_request_cao.assert_any_call("DELETE", "/terminals/leader1")
        mock_request_cao.assert_any_call(
            "POST",
            "/sessions/cao-team1/terminals",
            {"agent_profile": "reviewer", "provider": "codex", "working_directory": "/home/penn/workspace/team-a"},
        )
        mock_rekey.assert_called_once_with("leader1", "leader2")
        mock_set_team_alias.assert_called_once_with("leader2", "新团队")
        mock_set_team_workdir.assert_called_once_with("leader2", "/home/penn/workspace/team-a")
        mock_runtime.assert_called_once()


@pytest.mark.asyncio
async def test_restart_team_leader_task_recreates_session_when_missing() -> None:
    with (
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._response_json_or_text") as mock_json,
        patch(
            "cli_agent_orchestrator.control_panel.main._get_team_runtime",
            return_value={
                "leader_id": "leader1",
                "terminal_id": "leader1",
                "session_name": "cao-team1",
                "provider": "kiro_cli",
                "agent_profile": "code_supervisor",
                "working_directory": "/home/penn/workspace/team-a",
            },
        ),
        patch(
            "cli_agent_orchestrator.control_panel.main._list_team_working_directories",
            return_value={"leader1": "/home/penn/workspace/team-a"},
        ),
        patch("cli_agent_orchestrator.control_panel.main._list_live_sessions", return_value=set()),
        patch("cli_agent_orchestrator.control_panel.main._upsert_team_runtime") as mock_runtime,
    ):
        mock_request_cao.side_effect = [MagicMock(), MagicMock(), MagicMock()]
        mock_json.side_effect = [
            {
                "id": "leader1",
                "session_name": "cao-team1",
                "provider": "kiro_cli",
                "agent_profile": "code_supervisor",
            },
            {
                "id": "leader1",
                "session_name": "cao-team1",
                "provider": "kiro_cli",
                "agent_profile": "code_supervisor",
            },
        ]

        payload = control_panel_main.OrgLeaderUpdateRequest(agent_profile="code_supervisor")
        result = await control_panel_main._restart_team_leader_task(
            normalized_leader_id="leader1",
            payload=payload,
            requested_working_directory="/home/penn/workspace/team-a",
        )

        assert result["ok"] is True
        mock_request_cao.assert_any_call("DELETE", "/terminals/leader1")
        mock_request_cao.assert_any_call(
            "POST",
            "/sessions",
            {
                "agent_profile": "code_supervisor",
                "provider": "kiro_cli",
                "working_directory": "/home/penn/workspace/team-a",
                "session_name": "cao-team1",
            },
        )
        mock_runtime.assert_called_once()


def test_console_update_team_leader_returns_async_ack(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._list_teams", return_value={"leader1"}),
        patch("cli_agent_orchestrator.control_panel.main._resolve_terminal_id_alias", return_value="leader1"),
        patch(
            "cli_agent_orchestrator.control_panel.main._resolve_home_level1_directory",
            return_value="/home/penn/workspace/team-a",
        ),
        patch("cli_agent_orchestrator.control_panel.main.asyncio.create_task") as mock_create_task,
        patch("cli_agent_orchestrator.control_panel.main._restart_team_leader_task", new_callable=AsyncMock),
    ):
        mock_create_task.side_effect = lambda coro: (coro.close(), MagicMock())[1]

        response = client.put(
            "/console/organization/leader1/leader",
            json={
                "agent_profile": "reviewer",
                "provider": "codex",
                "team_workdir_mode": "existing",
                "team_workdir_name": "team-a",
            },
        )

        assert response.status_code == 202
        body = response.json()
        assert body["ok"] is True
        assert body["queued"] is True
        assert body["leader_id"] == "leader1"
        assert "后台重启" in body["message"]
        mock_create_task.assert_called_once()


def test_console_disband_team_deletes_target_session_only(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._response_json_or_text") as mock_json,
    ):
        mock_request_cao.side_effect = [MagicMock(), MagicMock(), MagicMock()]
        mock_json.side_effect = [
            {
                "id": "leader1",
                "agent_profile": "code_supervisor",
                "session_name": "cao-team1",
            },
            [
                {
                    "id": "leader1",
                    "agent_profile": "code_supervisor",
                    "session_name": "cao-team1",
                },
                {
                    "id": "worker1",
                    "agent_profile": "developer",
                    "session_name": "cao-team1",
                },
            ],
            {"success": True},
        ]

        response = client.post(
            "/console/organization/leader1/disband",
            json={"session_name": "cao-team1"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["leader_id"] == "leader1"
        assert body["session_name"] == "cao-team1"
        mock_request_cao.assert_any_call("DELETE", "/sessions/cao-team1")


def test_console_disband_team_allows_shared_multi_leader_session(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._response_json_or_text") as mock_json,
    ):
        mock_request_cao.side_effect = [MagicMock(), MagicMock()]
        mock_json.side_effect = [
            {
                "id": "leader1",
                "agent_profile": "code_supervisor",
                "session_name": "cao-shared",
            },
            {"success": True},
        ]

        response = client.post(
            "/console/organization/leader1/disband",
            json={"session_name": "cao-shared"},
        )

        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert mock_request_cao.call_count == 2


def test_console_disband_team_removes_team_persistence(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._response_json_or_text") as mock_json,
        patch("cli_agent_orchestrator.control_panel.main._remove_team") as mock_remove_team,
    ):
        mock_request_cao.side_effect = [MagicMock(), MagicMock()]
        mock_json.side_effect = [
            {
                "id": "leader1",
                "agent_profile": "code_supervisor",
                "session_name": "cao-team1",
            },
            {"success": True},
        ]

        response = client.post(
            "/console/organization/leader1/disband",
            json={"session_name": "cao-team1"},
        )

        assert response.status_code == 200
        assert response.json()["ok"] is True
        mock_remove_team.assert_called_once_with("leader1")


def test_console_disband_team_offline_uses_runtime_session_and_removes_team(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._list_teams", return_value={"leader-offline"}),
        patch("cli_agent_orchestrator.control_panel.main._resolve_terminal_id_alias", return_value="leader-offline"),
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._response_json_or_text"),
        patch("cli_agent_orchestrator.control_panel.main._get_team_runtime", return_value={"session_name": "cao-offline"}),
        patch("cli_agent_orchestrator.control_panel.main._list_live_sessions", return_value=set()),
        patch("cli_agent_orchestrator.control_panel.main._remove_team") as mock_remove_team,
    ):
        not_found_response = requests.Response()
        not_found_response.status_code = 404
        http_error = requests.exceptions.HTTPError("404 Not Found")
        http_error.response = not_found_response
        mock_request_cao.side_effect = [http_error]

        response = client.post("/console/organization/leader-offline/disband")

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["session_name"] == "cao-offline"
        assert body["result"]["session_deleted"] is False
        mock_remove_team.assert_called_once_with("leader-offline")


def test_console_disband_team_ignores_leader_terminal_500_and_still_removes_team(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._list_teams", return_value={"leader-offline"}),
        patch("cli_agent_orchestrator.control_panel.main._resolve_terminal_id_alias", return_value="leader-offline"),
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._get_team_runtime", return_value={"session_name": "cao-offline"}),
        patch("cli_agent_orchestrator.control_panel.main._list_live_sessions", return_value=set()),
        patch("cli_agent_orchestrator.control_panel.main._remove_team") as mock_remove_team,
    ):
        upstream_500 = requests.Response()
        upstream_500.status_code = 500
        http_error = requests.exceptions.HTTPError("500 Internal Server Error")
        http_error.response = upstream_500
        mock_request_cao.side_effect = [http_error]

        response = client.post("/console/organization/leader-offline/disband")

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["leader_id"] == "leader-offline"
        assert body["session_name"] == "cao-offline"
        assert body["result"]["session_deleted"] is False
        mock_remove_team.assert_called_once_with("leader-offline")


def test_console_clock_out_team_removes_workers_and_exits_leader(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._list_teams", return_value={"leader1"}),
        patch("cli_agent_orchestrator.control_panel.main._resolve_terminal_id_alias", return_value="leader1"),
        patch("cli_agent_orchestrator.control_panel.main._get_terminals_from_sessions", return_value=[]),
        patch(
            "cli_agent_orchestrator.control_panel.main._build_organization",
            return_value={
                "leader_groups": [
                    {
                        "leader": {
                            "id": "leader1",
                            "session_name": "cao-team1",
                            "provider": "kiro_cli",
                            "agent_profile": "code_supervisor",
                            "is_offline": False,
                        },
                        "members": [
                            {"id": "worker1"},
                            {"id": "worker2"},
                        ],
                    }
                ]
            },
        ),
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch(
            "cli_agent_orchestrator.control_panel.main._get_team_runtime",
            return_value={
                "leader_id": "leader1",
                "session_name": "cao-team1",
                "provider": "kiro_cli",
                "agent_profile": "code_supervisor",
                "working_directory": "/home/penn/workspace/team-a",
            },
        ),
        patch("cli_agent_orchestrator.control_panel.main._upsert_team_runtime") as mock_runtime,
        patch("cli_agent_orchestrator.control_panel.main._remove_worker_link") as mock_remove_worker_link,
    ):
        mock_request_cao.side_effect = [MagicMock(), MagicMock(), MagicMock()]

        response = client.post("/console/organization/leader1/clock-out")

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["leader_id"] == "leader1"
        assert body["session_name"] == "cao-team1"
        assert body["workers_removed"] == 2
        assert body["leader_terminal_exited"] is True
        mock_request_cao.assert_any_call("DELETE", "/terminals/worker1")
        mock_request_cao.assert_any_call("DELETE", "/terminals/worker2")
        mock_request_cao.assert_any_call("DELETE", "/terminals/leader1")
        mock_remove_worker_link.assert_any_call("worker1")
        mock_remove_worker_link.assert_any_call("worker2")
        mock_runtime.assert_called_once_with(
            "leader1",
            terminal_id=None,
            session_name="cao-team1",
            provider="kiro_cli",
            agent_profile="code_supervisor",
            working_directory="/home/penn/workspace/team-a",
        )


def test_console_clock_out_team_ignores_missing_worker_terminal(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._list_teams", return_value={"leader1"}),
        patch("cli_agent_orchestrator.control_panel.main._resolve_terminal_id_alias", return_value="leader1"),
        patch("cli_agent_orchestrator.control_panel.main._get_terminals_from_sessions", return_value=[]),
        patch(
            "cli_agent_orchestrator.control_panel.main._build_organization",
            return_value={
                "leader_groups": [
                    {
                        "leader": {
                            "id": "leader1",
                            "session_name": "cao-team1",
                            "provider": "kiro_cli",
                            "agent_profile": "code_supervisor",
                            "is_offline": True,
                        },
                        "members": [{"id": "worker1"}],
                    }
                ]
            },
        ),
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch(
            "cli_agent_orchestrator.control_panel.main._get_team_runtime",
            return_value={
                "leader_id": "leader1",
                "session_name": "cao-team1",
                "provider": "kiro_cli",
                "agent_profile": "code_supervisor",
                "working_directory": "/home/penn/workspace/team-a",
            },
        ),
        patch("cli_agent_orchestrator.control_panel.main._upsert_team_runtime") as mock_runtime,
        patch("cli_agent_orchestrator.control_panel.main._remove_worker_link") as mock_remove_worker_link,
    ):
        not_found_response = requests.Response()
        not_found_response.status_code = 404
        not_found_error = requests.exceptions.HTTPError("404 Not Found")
        not_found_error.response = not_found_response
        mock_request_cao.side_effect = [not_found_error]

        response = client.post("/console/organization/leader1/clock-out")

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["workers_removed"] == 0
        assert body["leader_terminal_exited"] is False
        assert body["result"]["workers_not_found"] == ["worker1"]
        mock_remove_worker_link.assert_called_once_with("worker1")
        mock_runtime.assert_called_once()


def test_console_organization_collapses_same_session_supervisors_into_single_team(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._list_worker_links", return_value={}),
        patch("cli_agent_orchestrator.control_panel.main._register_team"),
        patch("cli_agent_orchestrator.control_panel.main._set_worker_link") as mock_set_worker_link,
        patch("cli_agent_orchestrator.control_panel.main.requests.request") as mock_request,
    ):
        sessions = MagicMock()
        sessions.raise_for_status.return_value = None
        sessions.json.return_value = [{"name": "cao-shared"}]

        terminals = MagicMock()
        terminals.raise_for_status.return_value = None
        terminals.json.return_value = [
            {
                "id": "leader1",
                "provider": "kiro_cli",
                "agent_profile": "code_supervisor",
                "session_name": "cao-shared",
            },
            {
                "id": "leader2",
                "provider": "kiro_cli",
                "agent_profile": "ai_editor_supervisor",
                "session_name": "cao-shared",
            },
            {
                "id": "worker1",
                "provider": "codex",
                "agent_profile": "developer",
                "session_name": "cao-shared",
            },
        ]

        leader1_detail = MagicMock()
        leader1_detail.raise_for_status.return_value = None
        leader1_detail.json.return_value = {
            "id": "leader1",
            "status": "IDLE",
            "provider": "kiro_cli",
            "agent_profile": "code_supervisor",
            "session_name": "cao-shared",
        }

        leader2_detail = MagicMock()
        leader2_detail.raise_for_status.return_value = None
        leader2_detail.json.return_value = {
            "id": "leader2",
            "status": "IDLE",
            "provider": "kiro_cli",
            "agent_profile": "ai_editor_supervisor",
            "session_name": "cao-shared",
        }

        worker_detail = MagicMock()
        worker_detail.raise_for_status.return_value = None
        worker_detail.json.return_value = {
            "id": "worker1",
            "status": "PROCESSING",
            "provider": "codex",
            "agent_profile": "developer",
            "session_name": "cao-shared",
        }

        mock_request.side_effect = [
            sessions,
            terminals,
            leader1_detail,
            leader2_detail,
            worker_detail,
        ]

        response = client.get("/console/organization")

        assert response.status_code == 200
        body = response.json()
        assert len(body["leader_groups"]) == 1
        assert body["leader_groups"][0]["leader"]["id"] == "leader1"
        member_ids = [member["id"] for member in body["leader_groups"][0]["members"]]
        assert "leader2" in member_ids
        assert "worker1" in member_ids
        mock_set_worker_link.assert_any_call("leader2", "leader1")


def test_console_disband_team_rejects_leader_session_mismatch(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._response_json_or_text") as mock_json,
    ):
        mock_request_cao.return_value = MagicMock()
        mock_json.return_value = {
            "id": "leader1",
            "agent_profile": "developer",
            "session_name": "cao-team-real",
        }

        response = client.post(
            "/console/organization/leader1/disband",
            json={"session_name": "cao-team-other"},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "leader_id and session_name mismatch"


def test_console_ensure_team_online_restores_leader_and_rekeys(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._list_teams", return_value={"leader1"}),
        patch(
            "cli_agent_orchestrator.control_panel.main._get_team_runtime",
            return_value={
                "leader_id": "leader1",
                "terminal_id": "leader1",
                "session_name": "cao-team1",
                "provider": "kiro_cli",
                "agent_profile": "code_supervisor",
                "working_directory": "/home/test/team-a",
            },
        ),
        patch(
            "cli_agent_orchestrator.control_panel.main._get_terminal_db_metadata",
            return_value={
                "id": "leader1",
                "tmux_session": "cao-team1",
                "tmux_window": "code-supervisor",
                "provider": "kiro_cli",
                "agent_profile": "code_supervisor",
            },
        ),
        patch("cli_agent_orchestrator.control_panel.main._list_team_working_directories", return_value={}),
        patch("cli_agent_orchestrator.control_panel.main._list_live_sessions", return_value=set()),
        patch("cli_agent_orchestrator.control_panel.main._rekey_leader_id") as mock_rekey,
        patch("cli_agent_orchestrator.control_panel.main._upsert_team_runtime") as mock_runtime,
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._response_json_or_text") as mock_json,
    ):
        mock_request_cao.return_value = MagicMock()
        mock_json.return_value = {
            "id": "leader2",
            "session_name": "cao-team1",
            "provider": "kiro_cli",
            "agent_profile": "code_supervisor",
        }

        response = client.post("/console/organization/leader1/ensure-online")

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["restored"] is True
        assert body["leader_id"] == "leader2"
        assert body["terminal_id"] == "leader2"
        mock_rekey.assert_called_once_with("leader1", "leader2")
        mock_runtime.assert_called_once()


def test_console_ensure_team_online_reuses_live_terminal(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._list_teams", return_value={"leader1"}),
        patch(
            "cli_agent_orchestrator.control_panel.main._get_team_runtime",
            return_value={
                "leader_id": "leader1",
                "terminal_id": "leader1",
                "session_name": "cao-team1",
                "provider": "kiro_cli",
                "agent_profile": "developer",
                "working_directory": "/home/test/team-a",
            },
        ),
        patch(
            "cli_agent_orchestrator.control_panel.main._get_terminal_db_metadata",
            return_value={
                "id": "leader1",
                "tmux_session": "cao-team1",
                "tmux_window": "developer",
                "provider": "kiro_cli",
                "agent_profile": "developer",
            },
        ),
        patch("cli_agent_orchestrator.control_panel.main._list_team_working_directories", return_value={}),
        patch("cli_agent_orchestrator.control_panel.main._list_live_sessions", return_value={"cao-team1"}),
        patch("cli_agent_orchestrator.control_panel.main._rekey_leader_id") as mock_rekey,
        patch("cli_agent_orchestrator.control_panel.main._upsert_team_runtime") as mock_runtime,
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._response_json_or_text") as mock_json,
    ):
        mock_request_cao.side_effect = [MagicMock(), MagicMock()]
        mock_json.side_effect = [
            [
                {
                    "id": "leader1",
                    "agent_profile": "developer",
                    "session_name": "cao-team1",
                    "is_main": True,
                }
            ],
            {
                "id": "leader1",
                "session_name": "cao-team1",
                "provider": "kiro_cli",
                "agent_profile": "developer",
            },
        ]

        response = client.post("/console/organization/leader1/ensure-online")

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["restored"] is False
        assert body["leader_id"] == "leader1"
        assert body["terminal_id"] == "leader1"
        mock_rekey.assert_not_called()
        mock_runtime.assert_called_once()


def test_console_assets_team_listing(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._get_terminals_from_sessions", return_value=[]),
        patch(
            "cli_agent_orchestrator.control_panel.main._build_organization",
            return_value={
                "leaders": [],
                "workers": [],
                "unassigned_workers": [],
                "leader_groups": [
                    {
                        "leader": {
                            "id": "leader1",
                            "session_name": "cao-team1",
                            "agent_profile": "code_supervisor",
                            "provider": "kiro_cli",
                        },
                        "team_alias": "团队A",
                        "team_working_directory": "/tmp/team-a",
                        "members": [],
                    }
                ],
            },
        ),
    ):
        response = client.get("/console/assets/teams")
        assert response.status_code == 200
        body = response.json()
        assert len(body["teams"]) == 1
        assert body["teams"][0]["leader_id"] == "leader1"
        assert body["teams"][0]["working_directory"] == "/tmp/team-a"


def test_console_assets_tree_and_file_preview(client: TestClient, tmp_path: Path) -> None:
    login(client)

    team_root = tmp_path / "team-a"
    docs_dir = team_root / "docs"
    docs_dir.mkdir(parents=True)
    readme = docs_dir / "README.md"
    readme.write_text("hello team asset", encoding="utf-8")

    with patch(
        "cli_agent_orchestrator.control_panel.main._resolve_team_working_directory_for_assets",
        return_value=team_root,
    ):
        tree_response = client.get("/console/assets/teams/leader1/tree", params={"path": "docs"})
        assert tree_response.status_code == 200
        tree_body = tree_response.json()
        assert tree_body["path"] == "docs"
        assert len(tree_body["entries"]) == 1
        assert tree_body["entries"][0]["name"] == "README.md"
        assert tree_body["entries"][0]["is_dir"] is False

        file_response = client.get(
            "/console/assets/teams/leader1/file",
            params={"path": "docs/README.md"},
        )
        assert file_response.status_code == 200
        file_body = file_response.json()
        assert file_body["path"] == "docs/README.md"
        assert file_body["content"] == "hello team asset"


def test_console_assets_download_file(client: TestClient, tmp_path: Path) -> None:
    login(client)

    team_root = tmp_path / "team-a"
    team_root.mkdir(parents=True)
    binary_file = team_root / "artifact.bin"
    binary_file.write_bytes(b"\x00\x01\x02")

    with patch(
        "cli_agent_orchestrator.control_panel.main._resolve_team_working_directory_for_assets",
        return_value=team_root,
    ):
        response = client.get(
            "/console/assets/teams/leader1/download",
            params={"path": "artifact.bin"},
        )

        assert response.status_code == 200
        assert response.content == b"\x00\x01\x02"


def test_console_assets_preview_file_inline(client: TestClient, tmp_path: Path) -> None:
    login(client)

    team_root = tmp_path / "team-a"
    team_root.mkdir(parents=True)
    image_file = team_root / "diagram.png"
    image_file.write_bytes(b"\x89PNG\r\n\x1a\npreview")

    with patch(
        "cli_agent_orchestrator.control_panel.main._resolve_team_working_directory_for_assets",
        return_value=team_root,
    ):
        response = client.get(
            "/console/assets/teams/leader1/preview",
            params={"path": "diagram.png"},
        )

        assert response.status_code == 200
        assert response.content == b"\x89PNG\r\n\x1a\npreview"
        assert response.headers["content-type"].startswith("image/png")
        assert "inline" in response.headers.get("content-disposition", "")


def test_console_agent_profiles(client: TestClient) -> None:
    login(client)

    with patch(
        "cli_agent_orchestrator.control_panel.main._list_available_agent_profiles",
        return_value=["code_supervisor", "developer", "reviewer"],
    ), patch(
        "cli_agent_orchestrator.control_panel.main._list_available_agent_profile_options",
        return_value=[
            {"profile": "code_supervisor", "display_name": "负责人"},
            {"profile": "developer", "display_name": "工程师"},
            {"profile": "reviewer", "display_name": None},
        ],
    ):
        response = client.get("/console/agent-profiles")

        assert response.status_code == 200
        body = response.json()
        assert body["profiles"] == ["code_supervisor", "developer", "reviewer"]
        assert body["profile_options"] == [
            {"profile": "code_supervisor", "display_name": "负责人"},
            {"profile": "developer", "display_name": "工程师"},
            {"profile": "reviewer", "display_name": None},
        ]


def test_console_create_agent_profile(client: TestClient, tmp_path) -> None:
    login(client)

    with patch("cli_agent_orchestrator.control_panel.main.AGENT_CONTEXT_DIR", tmp_path):
        response = client.post(
            "/console/agent-profiles",
            json={
                "name": "data_analyst",
                "content": "---\nname: data_analyst\nprovider: codex\n---\n\n# DATA ANALYST\nFocus on metrics.",
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
        assert "provider: codex" in content
        assert "# DATA ANALYST" in content


def test_console_get_and_update_agent_profile(client: TestClient, tmp_path) -> None:
    login(client)

    profile_file = tmp_path / "designer.md"
    profile_file.write_text("---\nname: designer\ndescription: ui\n---\n\nhello\n", encoding="utf-8")

    with patch("cli_agent_orchestrator.control_panel.main.AGENT_CONTEXT_DIR", tmp_path):
        get_response = client.get("/console/agent-profiles/designer")
        assert get_response.status_code == 200
        assert "description: ui" in get_response.json()["content"]

        update_response = client.put(
            "/console/agent-profiles/designer",
            json={"content": "---\nname: designer\ndescription: ui2\n---\n\nupdated\n"},
        )
        assert update_response.status_code == 200
        assert "description: ui2" in profile_file.read_text(encoding="utf-8")

        list_response = client.get("/console/agent-profiles/files")
        assert list_response.status_code == 200
        assert list_response.json()["files"][0]["file_name"] == "designer.md"

        file_response = client.get("/console/agent-profiles/files/designer.md")
        assert file_response.status_code == 200
        assert file_response.json()["profile"] == "designer"


def test_console_create_agent_profile_stores_display_name(client: TestClient, tmp_path: Path) -> None:
    login(client)

    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    db_path = tmp_path / "org.sqlite"

    with (
        patch("cli_agent_orchestrator.control_panel.main.AGENT_CONTEXT_DIR", profile_dir),
        patch("cli_agent_orchestrator.control_panel.main.DB_DIR", tmp_path),
        patch("cli_agent_orchestrator.control_panel.main.DATABASE_FILE", db_path),
    ):
        control_panel_main._init_organization_db()
        response = client.post(
            "/console/agent-profiles",
            json={
                "name": "data_analyst",
                "content": "---\nname: data_analyst\nprovider: codex\n---\n\n# DATA ANALYST\nFocus on metrics.",
                "display_name": "数据分析岗",
            },
        )

        assert response.status_code == 200

        list_response = client.get("/console/agent-profiles/files")
        assert list_response.status_code == 200
        files = list_response.json()["files"]
        assert files[0]["display_name"] == "数据分析岗"

        file_response = client.get("/console/agent-profiles/files/data_analyst.md")
        assert file_response.status_code == 200
        assert file_response.json()["display_name"] == "数据分析岗"

        profile_file = profile_dir / "data_analyst.md"
        assert "name: data_analyst" in profile_file.read_text(encoding="utf-8")


def test_console_update_agent_profile_sets_display_name_without_touching_frontmatter(
    client: TestClient, tmp_path: Path
) -> None:
    login(client)

    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    db_path = tmp_path / "org.sqlite"

    profile_file = profile_dir / "designer.md"
    profile_file.write_text("---\nname: designer\ndescription: ui\n---\n\nhello\n", encoding="utf-8")

    with (
        patch("cli_agent_orchestrator.control_panel.main.AGENT_CONTEXT_DIR", profile_dir),
        patch("cli_agent_orchestrator.control_panel.main.DB_DIR", tmp_path),
        patch("cli_agent_orchestrator.control_panel.main.DATABASE_FILE", db_path),
    ):
        control_panel_main._init_organization_db()
        update_response = client.put(
            "/console/agent-profiles/designer",
            json={"content": profile_file.read_text(encoding="utf-8"), "display_name": "设计师"},
        )

        assert update_response.status_code == 200
        assert "name: designer" in profile_file.read_text(encoding="utf-8")

        list_response = client.get("/console/agent-profiles/files")
        assert list_response.status_code == 200
        files = list_response.json()["files"]
        assert files[0]["display_name"] == "设计师"

        file_response = client.get("/console/agent-profiles/files/designer.md")
        assert file_response.status_code == 200
        assert file_response.json()["display_name"] == "设计师"


def test_console_create_agent_profile_rejects_invalid_markdown(client: TestClient, tmp_path) -> None:
    login(client)

    with patch("cli_agent_orchestrator.control_panel.main.AGENT_CONTEXT_DIR", tmp_path):
        response = client.post(
            "/console/agent-profiles",
            json={
                "name": "bad_profile",
                "content": "# no frontmatter",
            },
        )

    assert response.status_code == 400
    assert "Invalid agent profile markdown" in response.json()["detail"]


def test_console_install_agent_profile(client: TestClient, tmp_path) -> None:
    login(client)

    profile_file = tmp_path / "ops.md"
    profile_file.write_text("---\nname: ops\ndescription: ops\n---\n\nrun\n", encoding="utf-8")

    with (
        patch("cli_agent_orchestrator.control_panel.main.AGENT_CONTEXT_DIR", tmp_path),
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


def test_console_agent_output_stream_stops_on_upstream_404(client: TestClient) -> None:
    login(client)

    with patch("cli_agent_orchestrator.control_panel.main.requests.request") as mock_request:
        output_response = MagicMock()
        output_response.status_code = 404
        output_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            "404 Client Error: Not Found",
            response=output_response,
        )
        mock_request.return_value = output_response

        with client.stream("GET", "/console/agents/missing/stream") as response:
            assert response.status_code == 200
            assert "text/event-stream" in response.headers.get("content-type", "")
            body = "".join(response.iter_text())
            assert body == ""

        assert mock_request.call_count == 1


def test_proxy_delete_request(client: TestClient) -> None:
    """Test proxying a DELETE request to cao-server."""
    login(client)

    with patch("cli_agent_orchestrator.control_panel.main.requests.request") as mock_request:
        mock_response = MagicMock()
        mock_response.status_code = 204
        mock_response.content = b""
        mock_response.headers = {}
        mock_request.return_value = mock_response

        response = client.delete("/api/sessions/test-session")

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
                        "leader": {
                            "id": "leader1",
                            "agent_profile": "code_supervisor",
                            "session_name": "cao-team1",
                        },
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
                "session_name": "cao-team1",
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


def test_console_tasks_handles_flow_fetch_failure(client: TestClient) -> None:
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
                        "leader": {
                            "id": "leader1",
                            "agent_profile": "code_supervisor",
                            "session_name": "cao-team1",
                        },
                        "members": [],
                    }
                ],
                "unassigned_workers": [],
            },
        ),
        patch(
            "cli_agent_orchestrator.control_panel.main._request_cao",
            side_effect=requests.exceptions.RequestException("boom"),
        ),
    ):
        response = client.get("/console/tasks")

        assert response.status_code == 200
        body = response.json()
        assert len(body["teams"]) == 1
        assert body["teams"][0]["leader"]["id"] == "leader1"
        assert body["teams"][0]["scheduled_tasks"] == []
        assert body["unassigned_scheduled_tasks"] == []


def test_list_latest_task_titles_reads_terminal_latest_tasks(tmp_path: Path) -> None:
    from cli_agent_orchestrator.control_panel.main import _list_latest_task_titles

    db_path = tmp_path / "control_panel_task_titles.db"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(
            """
            CREATE TABLE inbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                receiver_id TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE terminal_latest_tasks (
                receiver_id TEXT PRIMARY KEY,
                message TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO terminal_latest_tasks (receiver_id, message, updated_at)
            VALUES (?, ?, ?)
            """,
            (
                "worker1",
                "Implement the dashboard data sync and report progress",
                "2026-03-02 12:00:00",
            ),
        )
        conn.commit()

    with patch("cli_agent_orchestrator.control_panel.main.DATABASE_FILE", db_path):
        titles = _list_latest_task_titles(["worker1"])

    assert titles["worker1"].startswith("Implement the dashboard data sync")


def test_console_create_scheduled_task_success(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._response_json_or_text") as mock_json,
        patch("cli_agent_orchestrator.control_panel.main._save_flow_content_to_file") as mock_save_file,
        patch("cli_agent_orchestrator.control_panel.main._set_flow_execution_session_name") as mock_set_session,
    ):
        mock_save_file.return_value = Path("/tmp/console_flows/flowA.md")
        mock_set_session.return_value = Path("/tmp/console_flows/flowA.md")
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
                "flow_display_name": "早会提醒",
                "flow_content": "---\nname: flowA\nschedule: '*/5 * * * *'\nagent_profile: developer\n---\nhello",
                "session_name": "cao-team1",
                "leader_id": "leader1",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["flow"]["name"] == "flowA"
        assert body["saved_file_path"] == "/tmp/console_flows/flowA.md"
        mock_save_file.assert_called_once_with(
            "---\nname: flowA\nschedule: '*/5 * * * *'\nagent_profile: developer\n---\nhello",
            "cao-team1",
        )
        mock_set_session.assert_called_once_with(Path("/tmp/console_flows/flowA.md"), "cao-team1")


def test_console_create_scheduled_task_rejects_invalid_markdown(client: TestClient) -> None:
    login(client)

    with patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao:
        response = client.post(
            "/console/tasks/scheduled",
            json={
                "flow_display_name": "无效备注",
                "flow_content": "hello without frontmatter",
            },
        )

    assert response.status_code == 400
    assert "Invalid flow markdown" in response.json()["detail"]
    mock_request_cao.assert_not_called()


def test_console_list_scheduled_task_files(client: TestClient, tmp_path: Path) -> None:
    login(client)

    db_path = tmp_path / "org.sqlite"

    with (
        patch("cli_agent_orchestrator.control_panel.main.AGENT_FLOW_DIR", tmp_path),
        patch("cli_agent_orchestrator.control_panel.main.DB_DIR", tmp_path),
        patch("cli_agent_orchestrator.control_panel.main.DATABASE_FILE", db_path),
    ):
        control_panel_main._init_organization_db()
        control_panel_main._upsert_flow_display_name("daily", "每日任务")

        flow_dir = tmp_path
        flow_dir.mkdir(parents=True, exist_ok=True)
        (flow_dir / "daily.md").write_text(
            "---\nname: daily\nschedule: '0 8 * * *'\nagent_profile: developer\n---\n",
            encoding="utf-8",
        )
        (flow_dir / "nightly.md").write_text(
            "---\nname: nightly\nschedule: '0 9 * * *'\nagent_profile: developer\n---\n",
            encoding="utf-8",
        )
        session_dir = flow_dir / "cao-team1"
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "session.md").write_text(
            "---\nname: session\nschedule: '0 10 * * *'\nagent_profile: developer\n---\n",
            encoding="utf-8",
        )

        response = client.get("/console/tasks/scheduled/files")

        assert response.status_code == 200
        body = response.json()
        names = [item["file_name"] for item in body["files"]]
        assert names == ["cao-team1/session.md", "daily.md", "nightly.md"]
        daily_item = next(item for item in body["files"] if item["file_name"] == "daily.md")
        assert daily_item["flow_name"] == "daily"
        assert daily_item["display_name"] == "每日任务"


def test_console_create_scheduled_task_from_existing_file(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._resolve_console_flow_file") as mock_resolve_file,
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._response_json_or_text") as mock_json,
        patch("cli_agent_orchestrator.control_panel.main._set_flow_execution_session_name") as mock_set_session,
    ):
        mock_resolve_file.return_value = Path("/tmp/console_flows/existing-flow.md")
        mock_set_session.return_value = Path("/tmp/console_flows/existing-flow.md")
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
                "session_name": "cao-team1",
                "leader_id": "leader1",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["flow"]["name"] == "existing-flow"
        mock_resolve_file.assert_called_once_with("existing-flow.md")
        mock_set_session.assert_called_once_with(Path("/tmp/console_flows/existing-flow.md"), "cao-team1")


def test_console_get_scheduled_task_file_content(client: TestClient, tmp_path: Path) -> None:
    login(client)

    with patch("cli_agent_orchestrator.control_panel.main.AGENT_FLOW_DIR", tmp_path):
        flow_dir = tmp_path
        flow_dir.mkdir(parents=True, exist_ok=True)
        session_dir = flow_dir / "cao-team1"
        session_dir.mkdir(parents=True, exist_ok=True)
        flow_file = session_dir / "editable.md"
        flow_file.write_text("---\nname: editable\n---\n\nhello\n", encoding="utf-8")

        response = client.get("/console/tasks/scheduled/files/cao-team1/editable.md")

        assert response.status_code == 200
        body = response.json()
        assert body["file_name"] == "cao-team1/editable.md"
        assert body["flow_name"] == "editable"
        assert body["display_name"] is None
        assert "name: editable" in body["content"]


def test_console_create_scheduled_task_overwrites_selected_file_content(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._resolve_console_flow_file") as mock_resolve_file,
        patch("cli_agent_orchestrator.control_panel.main._overwrite_console_flow_file") as mock_overwrite_file,
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._response_json_or_text") as mock_json,
        patch("cli_agent_orchestrator.control_panel.main._set_flow_execution_session_name") as mock_set_session,
    ):
        selected_path = Path("/tmp/console_flows/editable.md")
        mock_resolve_file.return_value = selected_path
        mock_overwrite_file.return_value = selected_path
        mock_set_session.return_value = selected_path
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
                "session_name": "cao-team1",
                "leader_id": "leader1",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        mock_resolve_file.assert_called_once_with("editable.md")
        mock_overwrite_file.assert_called_once()
        mock_set_session.assert_called_once_with(selected_path, "cao-team1")


def test_console_create_scheduled_task_requires_session_when_leader_set(client: TestClient) -> None:
    login(client)

    response = client.post(
        "/console/tasks/scheduled",
        json={
            "flow_display_name": "团队任务",
            "flow_content": "---\nname: flowA\nschedule: '*/5 * * * *'\nagent_profile: developer\n---\nhello",
            "leader_id": "leader1",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "session_name is required when leader_id is provided"


def test_console_create_scheduled_task_recreates_on_duplicate_name(client: TestClient) -> None:
    login(client)

    duplicate_response = MagicMock()
    duplicate_response.json.return_value = {
        "detail": "(sqlite3.IntegrityError) UNIQUE constraint failed: flows.name"
    }
    duplicate_response.text = "UNIQUE constraint failed: flows.name"
    duplicate_error = requests.exceptions.HTTPError("500 Server Error")
    duplicate_error.response = duplicate_response

    with (
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._response_json_or_text") as mock_json,
        patch("cli_agent_orchestrator.control_panel.main._save_flow_content_to_file") as mock_save_file,
        patch("cli_agent_orchestrator.control_panel.main._set_flow_execution_session_name") as mock_set_session,
    ):
        mock_save_file.return_value = Path("/tmp/console_flows/morning-trivia.md")
        mock_set_session.return_value = Path("/tmp/console_flows/morning-trivia.md")
        mock_request_cao.side_effect = [duplicate_error, MagicMock(), MagicMock(), MagicMock()]
        mock_json.side_effect = [
            [],
            {
                "name": "morning-trivia",
                "file_path": "/tmp/console_flows/morning-trivia.md",
                "schedule": "52 0 * * *",
                "agent_profile": "ai_editor_supervisor",
                "provider": "kiro_cli",
                "enabled": True,
            },
        ]

        response = client.post(
            "/console/tasks/scheduled",
            json={
                "flow_display_name": "晨会任务",
                "flow_content": "---\nname: morning-trivia\nschedule: '52 0 * * *'\nagent_profile: ai_editor_supervisor\n---\n\nhello",
            },
        )

        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert mock_request_cao.call_count == 4
        assert mock_request_cao.call_args_list[1].args[0:2] == ("GET", "/flows")
        assert mock_request_cao.call_args_list[2].args[0:2] == ("DELETE", "/flows/morning-trivia")
        assert mock_request_cao.call_args_list[3].args[0:2] == ("POST", "/flows")


def test_console_create_scheduled_task_recreates_using_flow_name_from_file_path(client: TestClient) -> None:
    login(client)

    duplicate_response = MagicMock()
    duplicate_response.json.return_value = {
        "detail": "(sqlite3.IntegrityError) UNIQUE constraint failed: flows.name"
    }
    duplicate_response.text = "UNIQUE constraint failed: flows.name"
    duplicate_error = requests.exceptions.HTTPError("500 Server Error")
    duplicate_error.response = duplicate_response

    with (
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._response_json_or_text") as mock_json,
        patch("cli_agent_orchestrator.control_panel.main._save_flow_content_to_file") as mock_save_file,
        patch("cli_agent_orchestrator.control_panel.main._set_flow_execution_session_name") as mock_set_session,
    ):
        mock_save_file.return_value = Path("/tmp/console_flows/trivia.md")
        mock_set_session.return_value = Path("/tmp/console_flows/trivia.md")
        mock_request_cao.side_effect = [duplicate_error, MagicMock(), MagicMock(), MagicMock()]
        mock_json.side_effect = [
            [
                {
                    "name": "morning-trivia",
                    "file_path": "/tmp/console_flows/trivia.md",
                }
            ],
            {
                "name": "morning-trivia",
                "file_path": "/tmp/console_flows/trivia.md",
                "schedule": "52 0 * * *",
                "agent_profile": "ai_editor_supervisor",
                "provider": "kiro_cli",
                "enabled": True,
            },
        ]

        response = client.post(
            "/console/tasks/scheduled",
            json={
                "flow_display_name": "晨间问答",
                "flow_content": "---\nname: morning-trivia\nschedule: '52 0 * * *'\nagent_profile: ai_editor_supervisor\n---\n\nhello",
            },
        )

        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert mock_request_cao.call_args_list[1].args[0:2] == ("GET", "/flows")
        assert mock_request_cao.call_args_list[2].args[0:2] == ("DELETE", "/flows/morning-trivia")
        assert mock_request_cao.call_args_list[3].args[0:2] == ("POST", "/flows")


def test_console_create_scheduled_task_recreates_with_delete_404_fallback_to_frontmatter_name(
    client: TestClient,
) -> None:
    login(client)

    duplicate_response = MagicMock()
    duplicate_response.json.return_value = {
        "detail": "(sqlite3.IntegrityError) UNIQUE constraint failed: flows.name"
    }
    duplicate_response.text = "UNIQUE constraint failed: flows.name"
    duplicate_error = requests.exceptions.HTTPError("500 Server Error")
    duplicate_error.response = duplicate_response

    with (
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._response_json_or_text") as mock_json,
        patch("cli_agent_orchestrator.control_panel.main._save_flow_content_to_file") as mock_save_file,
        patch("cli_agent_orchestrator.control_panel.main._set_flow_execution_session_name") as mock_set_session,
    ):
        mock_save_file.return_value = Path("/tmp/console_flows/trivia.md")
        mock_set_session.return_value = Path("/tmp/console_flows/trivia.md")
        mock_request_cao.side_effect = [duplicate_error, MagicMock(), MagicMock(), MagicMock()]
        mock_json.side_effect = [
            [],
            {
                "name": "morning-trivia",
                "file_path": "/tmp/console_flows/trivia.md",
                "schedule": "52 0 * * *",
                "agent_profile": "ai_editor_supervisor",
                "provider": "kiro_cli",
                "enabled": True,
            },
        ]

        response = client.post(
            "/console/tasks/scheduled",
            json={
                "flow_display_name": "晨间问答",
                "flow_content": "---\nname: morning-trivia\nschedule: '52 0 * * *'\nagent_profile: ai_editor_supervisor\n---\n\nhello",
            },
        )

        assert response.status_code == 200
        assert response.json()["ok"] is True
    assert mock_request_cao.call_args_list[2].args[0:2] == ("DELETE", "/flows/morning-trivia")
    assert mock_request_cao.call_args_list[3].args[0:2] == ("POST", "/flows")


def test_console_run_enable_disable_scheduled_task_success(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._sync_bound_flow_session_name") as mock_sync_session,
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
        mock_sync_session.assert_called_once_with("flowA")


def test_console_create_scheduled_task_stores_display_name_and_uses_frontmatter_name(
    client: TestClient, tmp_path: Path
) -> None:
    login(client)

    flow_dir = tmp_path / "flows"
    db_path = tmp_path / "org.sqlite"

    with (
        patch("cli_agent_orchestrator.control_panel.main.AGENT_FLOW_DIR", flow_dir),
        patch("cli_agent_orchestrator.control_panel.main.DB_DIR", tmp_path),
        patch("cli_agent_orchestrator.control_panel.main.DATABASE_FILE", db_path),
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._response_json_or_text") as mock_json,
    ):
        control_panel_main._init_organization_db()
        mock_request_cao.return_value = MagicMock()
        mock_json.return_value = {
            "name": "morning-trivia",
            "file_path": str(flow_dir / "morning-trivia.md"),
            "schedule": "52 0 * * *",
            "agent_profile": "developer",
            "provider": "kiro_cli",
            "enabled": True,
        }

        response = client.post(
            "/console/tasks/scheduled",
            json={
                "flow_display_name": "早报提醒",
                "flow_content": "---\nname: morning-trivia\nschedule: '52 0 * * *'\nagent_profile: developer\n---\n\nhello",
            },
        )

        assert response.status_code == 200
        assert (flow_dir / "morning-trivia.md").exists()
        saved_content = (flow_dir / "morning-trivia.md").read_text(encoding="utf-8")
        assert "name: morning-trivia" in saved_content

        files_response = client.get("/console/tasks/scheduled/files")
        assert files_response.status_code == 200
        files = files_response.json()["files"]
        assert files[0]["file_name"] == "morning-trivia.md"
        assert files[0]["flow_name"] == "morning-trivia"
        assert files[0]["display_name"] == "早报提醒"


def test_console_update_scheduled_task_renames_file_to_frontmatter_name(client: TestClient, tmp_path: Path) -> None:
    login(client)

    flow_dir = tmp_path / "flows"
    flow_dir.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "org.sqlite"
    original_path = flow_dir / "old-name.md"
    original_path.write_text(
        "---\nname: old-name\nschedule: '0 8 * * *'\nagent_profile: developer\n---\n\nhello\n",
        encoding="utf-8",
    )

    with (
        patch("cli_agent_orchestrator.control_panel.main.AGENT_FLOW_DIR", flow_dir),
        patch("cli_agent_orchestrator.control_panel.main.DB_DIR", tmp_path),
        patch("cli_agent_orchestrator.control_panel.main.DATABASE_FILE", db_path),
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._response_json_or_text") as mock_json,
    ):
        control_panel_main._init_organization_db()
        control_panel_main._upsert_flow_display_name("old-name", "旧备注")
        mock_request_cao.return_value = MagicMock()
        mock_json.return_value = {
            "name": "new-name",
            "file_path": str(flow_dir / "new-name.md"),
            "schedule": "0 8 * * *",
            "agent_profile": "developer",
            "provider": "kiro_cli",
            "enabled": True,
        }

        response = client.post(
            "/console/tasks/scheduled",
            json={
                "file_name": "old-name.md",
                "flow_display_name": "新备注",
                "flow_content": "---\nname: new-name\nschedule: '0 8 * * *'\nagent_profile: developer\n---\n\nupdated",
            },
        )

        assert response.status_code == 200
        assert (flow_dir / "new-name.md").exists()
        assert original_path.exists() is False

        files_response = client.get("/console/tasks/scheduled/files")
        files = files_response.json()["files"]
        assert files[0]["file_name"] == "new-name.md"
        assert files[0]["display_name"] == "新备注"


def test_console_delete_scheduled_task_removes_display_name(client: TestClient, tmp_path: Path) -> None:
    login(client)

    db_path = tmp_path / "org.sqlite"

    with (
        patch("cli_agent_orchestrator.control_panel.main.DB_DIR", tmp_path),
        patch("cli_agent_orchestrator.control_panel.main.DATABASE_FILE", db_path),
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._response_json_or_text", return_value={"ok": True}),
    ):
        control_panel_main._init_organization_db()
        control_panel_main._upsert_flow_display_name("nightly", "夜间构建")
        mock_request_cao.return_value = MagicMock()

        response = client.delete("/console/tasks/scheduled/nightly")

        assert response.status_code == 200
        with sqlite3.connect(str(db_path)) as conn:
            row = conn.execute(
                "SELECT display_name FROM flow_display_names WHERE flow_name = ?",
                ("nightly",),
            ).fetchone()
        assert row is None


def test_console_delete_scheduled_task_success(client: TestClient) -> None:
    login(client)

    with (
        patch("cli_agent_orchestrator.control_panel.main._request_cao") as mock_request_cao,
        patch("cli_agent_orchestrator.control_panel.main._response_json_or_text", return_value={"success": True}),
    ):
        mock_request_cao.return_value = MagicMock()

        response = client.delete("/console/tasks/scheduled/flowA")

        assert response.status_code == 200
        assert response.json()["ok"] is True

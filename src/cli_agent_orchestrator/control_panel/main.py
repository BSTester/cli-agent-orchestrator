"""Control Panel FastAPI server - middleware layer between frontend and cao-server."""

import mimetypes
import logging
import os
import re
import secrets
import sqlite3
import subprocess
import asyncio
import json
import shutil
import time
import tomllib
import uuid
import contextlib
from collections import Counter
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlparse

import requests
import frontmatter
from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from cli_agent_orchestrator.constants import (
    AGENT_CONTEXT_DIR,
    AGENT_FLOW_DIR,
    API_BASE_URL,
    DATABASE_FILE,
    DB_DIR,
    DEFAULT_PROVIDER,
)
from cli_agent_orchestrator.clients.tmux import tmux_client
from cli_agent_orchestrator.services import terminal_service
from cli_agent_orchestrator.utils.provider_runtime_config import (
    get_provider_runtime_settings,
    load_provider_runtime_config,
    set_onboarding_state,
    update_provider_runtime_settings,
)

logger = logging.getLogger(__name__)

# Control panel server configuration
CONTROL_PANEL_HOST = os.getenv("CONTROL_PANEL_HOST", "localhost")
CONTROL_PANEL_PORT = int(os.getenv("CONTROL_PANEL_PORT", "8000"))
CONTROL_PANEL_STATIC_DIR = Path(
    os.getenv("CONTROL_PANEL_STATIC_DIR", str(Path(__file__).parent / "static"))
)

# CAO server URL (the actual backend)
CAO_SERVER_URL = os.getenv("CAO_SERVER_URL", API_BASE_URL)
CONSOLE_PASSWORD = os.getenv("CAO_CONSOLE_PASSWORD", "admin")
SESSION_COOKIE_NAME = "cao_console_session"
SESSION_TTL_SECONDS = int(os.getenv("CAO_CONSOLE_SESSION_TTL_SECONDS", "43200"))
WS_TOKEN_TTL_SECONDS = int(os.getenv("CAO_WS_TOKEN_TTL_SECONDS", "120"))

# CORS origins for frontend
CONTROL_PANEL_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

BUILTIN_AGENT_PROFILES = ("code_supervisor", "developer", "reviewer")
TASK_TITLE_MAX_LEN = 48
TASK_TITLE_FALLBACK_LEN = 20

CONTROL_PANEL_PROVIDER_GUIDES: List[Dict[str, Any]] = [
    {
        "id": "claude_code",
        "label": "Claude Code",
        "command": "claude",
        "supports_account_login": True,
        "supports_api_config": True,
        "default_selected": True,
        "login_command": "claude login",
        "logout_command": "claude logout",
    },
    {
        "id": "codex",
        "label": "Codex",
        "command": "codex",
        "supports_account_login": True,
        "supports_api_config": True,
        "default_selected": True,
        "login_command": "codex login",
        "logout_command": "codex logout",
    },
    {
        "id": "openclaw",
        "label": "OpenClaw",
        "command": "openclaw",
        "supports_account_login": False,
        "supports_api_config": True,
        "default_selected": True,
        "login_command": None,
        "logout_command": None,
    },
    {
        "id": "copilot",
        "label": "Copilot CLI",
        "command": "copilot",
        "supports_account_login": True,
        "supports_api_config": False,
        "default_selected": True,
        "login_command": "copilot login",
        "logout_command": "copilot logout",
        "logout_supported_override": True,
    },
    {
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
    },
    {
        "id": "kiro_cli",
        "label": "Kiro CLI",
        "command": "kiro-cli",
        "supports_account_login": True,
        "supports_api_config": False,
        "default_selected": True,
        "login_command": "kiro-cli login",
        "logout_command": "kiro-cli logout",
    },
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
    },
]

app = FastAPI(
    title="CAO Control Panel API",
    description="FastAPI interface layer for the CAO frontend control panel",
    version="1.0.0",
)

if CONSOLE_PASSWORD == "admin":
    logger.warning(
        "CAO_CONSOLE_PASSWORD not set. Using insecure default password 'admin'. "
        "Set CAO_CONSOLE_PASSWORD in production."
    )

_service_started_at = datetime.now(timezone.utc)
_sessions: Dict[str, float] = {}
_ws_tokens: Dict[str, float] = {}


def _init_organization_db() -> None:
    DB_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS org_teams (
                leader_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS org_worker_links (
                worker_id TEXT PRIMARY KEY,
                leader_id TEXT NOT NULL,
                linked_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS flow_team_links (
                flow_name TEXT PRIMARY KEY,
                leader_id TEXT,
                linked_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS org_team_aliases (
                leader_id TEXT PRIMARY KEY,
                alias TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS org_agent_aliases (
                agent_id TEXT PRIMARY KEY,
                alias TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS org_team_workdirs (
                leader_id TEXT PRIMARY KEY,
                working_directory TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS org_team_runtime (
                leader_id TEXT PRIMARY KEY,
                terminal_id TEXT,
                session_name TEXT,
                provider TEXT,
                agent_profile TEXT,
                working_directory TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS org_terminal_id_aliases (
                old_terminal_id TEXT PRIMARY KEY,
                new_terminal_id TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS agent_profile_display_names (
                profile TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS flow_display_names (
                flow_name TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        # Migrate historical flow-team links into flows.session_name as single source.
        flows_table_row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='flows'"
        ).fetchone()
        if flows_table_row:
            flow_columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(flows)").fetchall()
            }
            if "session_name" not in flow_columns:
                conn.execute("ALTER TABLE flows ADD COLUMN session_name TEXT")

            migration_rows = conn.execute(
                "SELECT flow_name, leader_id FROM flow_team_links WHERE leader_id IS NOT NULL"
            ).fetchall()
            for flow_name, leader_id in migration_rows:
                if not flow_name or not leader_id:
                    continue
                leader_row = conn.execute(
                    "SELECT tmux_session FROM terminals WHERE id = ?",
                    (str(leader_id),),
                ).fetchone()
                if not leader_row:
                    continue
                session_name = str(leader_row[0] or "").strip()
                if not session_name:
                    continue
                conn.execute(
                    """
                    UPDATE flows
                    SET session_name = ?
                    WHERE name = ? AND (session_name IS NULL OR session_name = '')
                    """,
                    (session_name, str(flow_name)),
                )
        conn.commit()


def _register_team(leader_id: str) -> None:
    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        conn.execute(
            """
            INSERT INTO org_teams (leader_id, created_at)
            VALUES (?, ?)
            ON CONFLICT(leader_id) DO NOTHING
            """,
            (leader_id, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def _set_worker_link(worker_id: str, leader_id: str) -> None:
    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        conn.execute(
            """
            INSERT INTO org_worker_links (worker_id, leader_id, linked_at)
            VALUES (?, ?, ?)
            ON CONFLICT(worker_id) DO UPDATE SET
                leader_id=excluded.leader_id,
                linked_at=excluded.linked_at
            """,
            (worker_id, leader_id, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def _remove_worker_link(worker_id: str) -> None:
    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        conn.execute("DELETE FROM org_worker_links WHERE worker_id = ?", (worker_id,))
        conn.commit()


def _list_worker_links() -> Dict[str, str]:
    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        rows = conn.execute("SELECT worker_id, leader_id FROM org_worker_links").fetchall()
    return {str(worker_id): str(leader_id) for worker_id, leader_id in rows}


def _list_teams() -> set[str]:
    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        rows = conn.execute("SELECT leader_id FROM org_teams").fetchall()
    return {str(leader_id) for (leader_id,) in rows}


def _remove_team(leader_id: str) -> None:
    normalized_leader_id = (leader_id or "").strip()
    if not normalized_leader_id:
        return

    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        conn.execute("DELETE FROM org_teams WHERE leader_id = ?", (normalized_leader_id,))
        conn.execute("DELETE FROM org_worker_links WHERE leader_id = ?", (normalized_leader_id,))
        conn.execute("DELETE FROM org_team_aliases WHERE leader_id = ?", (normalized_leader_id,))
        conn.execute("DELETE FROM org_team_workdirs WHERE leader_id = ?", (normalized_leader_id,))
        conn.execute("DELETE FROM org_team_runtime WHERE leader_id = ?", (normalized_leader_id,))
        conn.execute(
            "DELETE FROM flow_team_links WHERE leader_id = ?",
            (normalized_leader_id,),
        )
        conn.commit()


def _set_flow_team_link(flow_name: str, leader_id: Optional[str]) -> None:
    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        conn.execute(
            """
            INSERT INTO flow_team_links (flow_name, leader_id, linked_at)
            VALUES (?, ?, ?)
            ON CONFLICT(flow_name) DO UPDATE SET
                leader_id=excluded.leader_id,
                linked_at=excluded.linked_at
            """,
            (flow_name, leader_id, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def _remove_flow_team_link(flow_name: str) -> None:
    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        conn.execute("DELETE FROM flow_team_links WHERE flow_name = ?", (flow_name,))
        conn.commit()


def _list_flow_team_links() -> Dict[str, Optional[str]]:
    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        rows = conn.execute("SELECT flow_name, leader_id FROM flow_team_links").fetchall()
    return {str(flow_name): (str(leader_id) if leader_id else None) for flow_name, leader_id in rows}


def _set_team_alias(leader_id: str, alias: str) -> None:
    normalized_alias = alias.strip()
    if not normalized_alias:
        return
    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        conn.execute(
            """
            INSERT INTO org_team_aliases (leader_id, alias, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(leader_id) DO UPDATE SET
                alias=excluded.alias,
                updated_at=excluded.updated_at
            """,
            (leader_id, normalized_alias, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def _list_team_aliases() -> Dict[str, str]:
    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        rows = conn.execute("SELECT leader_id, alias FROM org_team_aliases").fetchall()
    return {str(leader_id): str(alias) for leader_id, alias in rows if leader_id and alias}


def _set_agent_alias(agent_id: str, alias: str) -> None:
    normalized_alias = alias.strip()
    if not normalized_alias:
        return
    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        conn.execute(
            """
            INSERT INTO org_agent_aliases (agent_id, alias, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET
                alias=excluded.alias,
                updated_at=excluded.updated_at
            """,
            (agent_id, normalized_alias, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()


def _list_agent_aliases() -> Dict[str, str]:
    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        rows = conn.execute("SELECT agent_id, alias FROM org_agent_aliases").fetchall()
    return {str(agent_id): str(alias) for agent_id, alias in rows if agent_id and alias}


def _set_team_working_directory(leader_id: str, working_directory: str) -> None:
    normalized_working_directory = working_directory.strip()
    if not normalized_working_directory:
        return

    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        conn.execute(
            """
            INSERT INTO org_team_workdirs (leader_id, working_directory, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(leader_id) DO UPDATE SET
                working_directory=excluded.working_directory,
                updated_at=excluded.updated_at
            """,
            (
                leader_id,
                normalized_working_directory,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def _list_team_working_directories() -> Dict[str, str]:
    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        rows = conn.execute("SELECT leader_id, working_directory FROM org_team_workdirs").fetchall()
    return {
        str(leader_id): str(working_directory)
        for leader_id, working_directory in rows
        if leader_id and working_directory
    }


def _upsert_profile_display_name(profile: str, display_name: Optional[str]) -> None:
    normalized_profile = (profile or "").strip()
    if not normalized_profile or display_name is None:
        return

    normalized_display_name = str(display_name).strip()
    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        if normalized_display_name:
            conn.execute(
                """
                INSERT INTO agent_profile_display_names (profile, display_name, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(profile) DO UPDATE SET
                    display_name=excluded.display_name,
                    updated_at=excluded.updated_at
                """,
                (normalized_profile, normalized_display_name, datetime.now(timezone.utc).isoformat()),
            )
        else:
            conn.execute("DELETE FROM agent_profile_display_names WHERE profile = ?", (normalized_profile,))
        conn.commit()


def _get_profile_display_name(profile: str) -> Optional[str]:
    normalized_profile = (profile or "").strip()
    if not normalized_profile:
        return None

    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        row = conn.execute(
            "SELECT display_name FROM agent_profile_display_names WHERE profile = ?",
            (normalized_profile,),
        ).fetchone()
    if not row or not row[0]:
        return None
    display_name = str(row[0]).strip()
    return display_name or None


def _remove_profile_display_name(profile: str) -> None:
    normalized_profile = (profile or "").strip()
    if not normalized_profile:
        return

    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        conn.execute("DELETE FROM agent_profile_display_names WHERE profile = ?", (normalized_profile,))
        conn.commit()


def _resolve_profile_display_name(profile: str, profile_path: Path) -> Optional[str]:
    stored_display_name = _get_profile_display_name(profile)
    if stored_display_name:
        return stored_display_name
    return _extract_profile_display_name(profile_path)


def _upsert_flow_display_name(flow_name: str, display_name: Optional[str]) -> None:
    normalized_flow_name = (flow_name or "").strip()
    if not normalized_flow_name or display_name is None:
        return

    normalized_display_name = str(display_name).strip()
    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        if normalized_display_name:
            conn.execute(
                """
                INSERT INTO flow_display_names (flow_name, display_name, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(flow_name) DO UPDATE SET
                    display_name=excluded.display_name,
                    updated_at=excluded.updated_at
                """,
                (normalized_flow_name, normalized_display_name, datetime.now(timezone.utc).isoformat()),
            )
        else:
            conn.execute("DELETE FROM flow_display_names WHERE flow_name = ?", (normalized_flow_name,))
        conn.commit()


def _get_flow_display_name(flow_name: str) -> Optional[str]:
    normalized_flow_name = (flow_name or "").strip()
    if not normalized_flow_name:
        return None

    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        row = conn.execute(
            "SELECT display_name FROM flow_display_names WHERE flow_name = ?",
            (normalized_flow_name,),
        ).fetchone()
    if not row or not row[0]:
        return None
    display_name = str(row[0]).strip()
    return display_name or None


def _remove_flow_display_name(flow_name: str) -> None:
    normalized_flow_name = (flow_name or "").strip()
    if not normalized_flow_name:
        return

    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        conn.execute("DELETE FROM flow_display_names WHERE flow_name = ?", (normalized_flow_name,))
        conn.commit()


def _upsert_team_runtime(
    leader_id: str,
    *,
    terminal_id: Optional[str],
    session_name: Optional[str],
    provider: Optional[str],
    agent_profile: Optional[str],
    working_directory: Optional[str],
) -> None:
    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        conn.execute(
            """
            INSERT INTO org_team_runtime (
                leader_id,
                terminal_id,
                session_name,
                provider,
                agent_profile,
                working_directory,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(leader_id) DO UPDATE SET
                terminal_id=excluded.terminal_id,
                session_name=excluded.session_name,
                provider=excluded.provider,
                agent_profile=excluded.agent_profile,
                working_directory=excluded.working_directory,
                updated_at=excluded.updated_at
            """,
            (
                leader_id,
                terminal_id,
                session_name,
                provider,
                agent_profile,
                working_directory,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def _get_team_runtime(leader_id: str) -> Optional[Dict[str, Optional[str]]]:
    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        row = conn.execute(
            """
            SELECT leader_id, terminal_id, session_name, provider, agent_profile, working_directory
            FROM org_team_runtime
            WHERE leader_id = ?
            """,
            (leader_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "leader_id": str(row[0]),
        "terminal_id": str(row[1]) if row[1] else None,
        "session_name": str(row[2]) if row[2] else None,
        "provider": str(row[3]) if row[3] else None,
        "agent_profile": str(row[4]) if row[4] else None,
        "working_directory": str(row[5]) if row[5] else None,
    }


def _add_terminal_id_alias(old_terminal_id: str, new_terminal_id: str) -> None:
    normalized_old = (old_terminal_id or "").strip()
    normalized_new = (new_terminal_id or "").strip()
    if not normalized_old or not normalized_new or normalized_old == normalized_new:
        return

    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        conn.execute(
            """
            INSERT INTO org_terminal_id_aliases (old_terminal_id, new_terminal_id, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(old_terminal_id) DO UPDATE SET
                new_terminal_id=excluded.new_terminal_id,
                updated_at=excluded.updated_at
            """,
            (
                normalized_old,
                normalized_new,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def _resolve_terminal_id_alias(terminal_id: str) -> str:
    current = (terminal_id or "").strip()
    if not current:
        return current

    visited: set[str] = set()
    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        while current and current not in visited:
            visited.add(current)
            row = conn.execute(
                "SELECT new_terminal_id FROM org_terminal_id_aliases WHERE old_terminal_id = ?",
                (current,),
            ).fetchone()
            if not row or not row[0]:
                break
            current = str(row[0]).strip()
    return current


def _get_terminal_db_metadata(terminal_id: str) -> Optional[Dict[str, str]]:
    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        row = conn.execute(
            """
            SELECT id, tmux_session, tmux_window, provider, agent_profile
            FROM terminals
            WHERE id = ?
            """,
            (terminal_id,),
        ).fetchone()

    if not row:
        return None

    return {
        "id": str(row[0]),
        "tmux_session": str(row[1] or ""),
        "tmux_window": str(row[2] or ""),
        "provider": str(row[3] or ""),
        "agent_profile": str(row[4] or ""),
    }


def _resolve_team_working_directory_for_assets(leader_id: str) -> Path:
    team_workdirs = _list_team_working_directories()
    workdir = (team_workdirs.get(leader_id) or "").strip()
    if not workdir:
        runtime = _get_team_runtime(leader_id)
        workdir = (runtime or {}).get("working_directory") or ""
        workdir = workdir.strip()
    if not workdir:
        raise HTTPException(status_code=404, detail="Team working directory not configured")

    root = Path(workdir).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise HTTPException(status_code=404, detail="Team working directory not found")
    return root


def _resolve_asset_relative_path(relative_path: str) -> str:
    normalized = (relative_path or "").strip()
    if not normalized:
        return ""
    if normalized.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid path")

    target = Path(normalized)
    if any(part in {"", ".", ".."} for part in target.parts):
        raise HTTPException(status_code=400, detail="Invalid path")

    return target.as_posix()


def _resolve_asset_target(root: Path, relative_path: str) -> Path:
    normalized = _resolve_asset_relative_path(relative_path)
    target = (root / normalized).resolve() if normalized else root
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Path out of team working directory")
    return target


def _rekey_leader_id(old_leader_id: str, new_leader_id: str) -> None:
    old_id = (old_leader_id or "").strip()
    new_id = (new_leader_id or "").strip()
    if not old_id or not new_id or old_id == new_id:
        return

    with sqlite3.connect(str(DATABASE_FILE)) as conn:
        conn.execute("INSERT OR IGNORE INTO org_teams (leader_id, created_at) VALUES (?, ?)", (new_id, datetime.now(timezone.utc).isoformat()))
        conn.execute("UPDATE org_worker_links SET leader_id = ? WHERE leader_id = ?", (new_id, old_id))
        conn.execute("UPDATE flow_team_links SET leader_id = ? WHERE leader_id = ?", (new_id, old_id))

        alias_row = conn.execute(
            "SELECT alias, updated_at FROM org_team_aliases WHERE leader_id = ?",
            (old_id,),
        ).fetchone()
        if alias_row and alias_row[0]:
            conn.execute(
                """
                INSERT INTO org_team_aliases (leader_id, alias, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(leader_id) DO UPDATE SET alias=excluded.alias, updated_at=excluded.updated_at
                """,
                (new_id, str(alias_row[0]), datetime.now(timezone.utc).isoformat()),
            )

        workdir_row = conn.execute(
            "SELECT working_directory FROM org_team_workdirs WHERE leader_id = ?",
            (old_id,),
        ).fetchone()
        if workdir_row and workdir_row[0]:
            conn.execute(
                """
                INSERT INTO org_team_workdirs (leader_id, working_directory, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(leader_id) DO UPDATE SET working_directory=excluded.working_directory, updated_at=excluded.updated_at
                """,
                (new_id, str(workdir_row[0]), datetime.now(timezone.utc).isoformat()),
            )

        runtime_row = conn.execute(
            """
            SELECT terminal_id, session_name, provider, agent_profile, working_directory
            FROM org_team_runtime
            WHERE leader_id = ?
            """,
            (old_id,),
        ).fetchone()
        if runtime_row:
            conn.execute(
                """
                INSERT INTO org_team_runtime (
                    leader_id,
                    terminal_id,
                    session_name,
                    provider,
                    agent_profile,
                    working_directory,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(leader_id) DO UPDATE SET
                    terminal_id=excluded.terminal_id,
                    session_name=excluded.session_name,
                    provider=excluded.provider,
                    agent_profile=excluded.agent_profile,
                    working_directory=excluded.working_directory,
                    updated_at=excluded.updated_at
                """,
                (
                    new_id,
                    runtime_row[0],
                    runtime_row[1],
                    runtime_row[2],
                    runtime_row[3],
                    runtime_row[4],
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

        conn.execute("DELETE FROM org_teams WHERE leader_id = ?", (old_id,))
        conn.execute("DELETE FROM org_team_aliases WHERE leader_id = ?", (old_id,))
        conn.execute("DELETE FROM org_team_workdirs WHERE leader_id = ?", (old_id,))
        conn.execute("DELETE FROM org_team_runtime WHERE leader_id = ?", (old_id,))
        conn.commit()

    _add_terminal_id_alias(old_id, new_id)


def _home_directory() -> Path:
    workspace_dir = (Path.home() / "workspace").resolve()
    workspace_dir.mkdir(parents=True, exist_ok=True)
    return workspace_dir


def _resolve_home_level1_directory(
    dir_name: str,
    *,
    must_exist: bool,
    create_if_missing: bool,
) -> str:
    normalized_name = (dir_name or "").strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="team_workdir_name cannot be empty")

    if normalized_name in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid team_workdir_name")

    if Path(normalized_name).name != normalized_name:
        raise HTTPException(
            status_code=400,
            detail="team_workdir_name must be a single directory name under workspace",
        )

    home_dir = _home_directory()
    candidate = (home_dir / normalized_name).resolve()

    try:
        relative_parts = candidate.relative_to(home_dir).parts
    except ValueError:
        raise HTTPException(status_code=400, detail="Directory must be under workspace directory")

    if len(relative_parts) != 1:
        raise HTTPException(
            status_code=400,
            detail="team_workdir_name must target a first-level directory under workspace",
        )

    if create_if_missing:
        candidate.mkdir(parents=False, exist_ok=True)

    if must_exist and not candidate.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Directory does not exist under workspace: {normalized_name}",
        )

    if candidate.exists() and not candidate.is_dir():
        raise HTTPException(status_code=400, detail=f"Path is not a directory: {normalized_name}")

    return str(candidate)


def _list_home_first_level_directories() -> List[Dict[str, str]]:
    home_dir = _home_directory()
    items: List[Dict[str, str]] = []

    for child in sorted(home_dir.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_dir():
            continue
        items.append({"name": child.name, "path": str(child.resolve())})

    return items


def _infer_worker_leader_links_from_inbox(
    leader_ids: set[str],
    worker_ids: set[str],
) -> Dict[str, str]:
    if not leader_ids or not worker_ids:
        return {}

    inferred: Dict[str, str] = {}
    try:
        with sqlite3.connect(str(DATABASE_FILE)) as conn:
            rows = conn.execute(
                """
                SELECT sender_id, receiver_id
                FROM inbox
                ORDER BY created_at DESC, id DESC
                """
            ).fetchall()
    except sqlite3.Error:
        return {}

    for sender_id, receiver_id in rows:
        sender = str(sender_id or "")
        receiver = str(receiver_id or "")

        if sender in leader_ids and receiver in worker_ids and receiver not in inferred:
            inferred[receiver] = sender
            continue

        if receiver in leader_ids and sender in worker_ids and sender not in inferred:
            inferred[sender] = receiver

    return inferred


def _summarize_task_title(message: str) -> str:
    normalized = (message or "").replace("\r\n", "\n").strip()
    if not normalized:
        return ""

    first_line = ""
    for line in normalized.split("\n"):
        if line.strip():
            first_line = line.strip()
            break

    compact = re.sub(r"\s+", " ", first_line).strip()
    if not compact:
        return normalized[:TASK_TITLE_FALLBACK_LEN]

    if len(compact) <= TASK_TITLE_MAX_LEN:
        return compact
    return f"{compact[:TASK_TITLE_MAX_LEN]}..."


def _list_latest_task_titles(receiver_ids: List[str]) -> Dict[str, str]:
    targets = [receiver_id for receiver_id in receiver_ids if receiver_id]
    if not targets:
        return {}

    placeholders = ",".join("?" for _ in targets)

    try:
        with sqlite3.connect(str(DATABASE_FILE)) as conn:
            rows = conn.execute(
                f"""
                SELECT receiver_id, message
                FROM (
                    SELECT
                        receiver_id,
                        message,
                        event_at,
                        ROW_NUMBER() OVER (
                            PARTITION BY receiver_id
                            ORDER BY event_at DESC
                        ) AS rn
                    FROM (
                        SELECT
                            receiver_id,
                            message,
                            datetime(created_at) AS event_at
                        FROM inbox
                        WHERE receiver_id IN ({placeholders})

                        UNION ALL

                        SELECT
                            receiver_id,
                            message,
                            datetime(updated_at) AS event_at
                        FROM terminal_latest_tasks
                        WHERE receiver_id IN ({placeholders})
                    ) merged
                ) ranked
                WHERE rn = 1
                """,
                targets + targets,
            ).fetchall()
    except sqlite3.Error:
        try:
            with sqlite3.connect(str(DATABASE_FILE)) as conn:
                rows = conn.execute(
                    f"""
                    SELECT receiver_id, message
                    FROM (
                        SELECT
                            receiver_id,
                            message,
                            ROW_NUMBER() OVER (
                                PARTITION BY receiver_id
                                ORDER BY created_at DESC, id DESC
                            ) AS rn
                        FROM inbox
                        WHERE receiver_id IN ({placeholders})
                    ) ranked
                    WHERE rn = 1
                    """,
                    targets,
                ).fetchall()
        except sqlite3.Error:
            return {}

    result: Dict[str, str] = {}
    for receiver_id, message in rows:
        terminal_id = str(receiver_id or "")
        task_title = _summarize_task_title(str(message or ""))
        if terminal_id and task_title:
            result[terminal_id] = task_title

    return result


def _session_similarity_score(leader_session: str, worker_session: str) -> int:
    if not leader_session or not worker_session:
        return 0

    if leader_session == worker_session:
        return 1000

    if worker_session.startswith(leader_session) or leader_session.startswith(worker_session):
        return 500

    prefix_len = 0
    for leader_char, worker_char in zip(leader_session, worker_session):
        if leader_char != worker_char:
            break
        prefix_len += 1

    return prefix_len


def _infer_worker_leader_links_from_session_name(
    leaders: List[Dict[str, Any]],
    workers: List[Dict[str, Any]],
    already_inferred: Dict[str, str],
) -> Dict[str, str]:
    inferred: Dict[str, str] = {}
    if not leaders or not workers:
        return inferred

    leader_candidates = [
        (str(leader.get("id", "")), str(leader.get("session_name", "")))
        for leader in leaders
        if leader.get("id") and leader.get("session_name")
    ]
    if not leader_candidates:
        return inferred

    for worker in workers:
        worker_id = str(worker.get("id", ""))
        if not worker_id or worker_id in already_inferred:
            continue

        worker_session = str(worker.get("session_name", ""))
        if not worker_session:
            continue

        scored: List[tuple[int, str]] = []
        for leader_id, leader_session in leader_candidates:
            score = _session_similarity_score(leader_session, worker_session)
            if score > 3:
                scored.append((score, leader_id))

        if not scored:
            continue

        scored.sort(key=lambda item: item[0], reverse=True)
        top_score, top_leader_id = scored[0]
        second_score = scored[1][0] if len(scored) > 1 else -1

        if top_score > second_score:
            inferred[worker_id] = top_leader_id

    return inferred


def _list_available_agent_profiles() -> List[str]:
    names: set[str] = set(BUILTIN_AGENT_PROFILES)

    try:
        builtin_store = resources.files("cli_agent_orchestrator.agent_store")
        for child in builtin_store.iterdir():
            child_name = str(child.name)
            if child_name.endswith(".md"):
                names.add(Path(child_name).stem)
    except Exception as exc:
        logger.warning("Failed to list built-in agent profiles: %s", exc)

    try:
        if AGENT_CONTEXT_DIR.exists():
            for child in AGENT_CONTEXT_DIR.iterdir():
                if child.is_file() and child.suffix == ".md":
                    names.add(child.stem)
    except Exception as exc:
        logger.warning("Failed to list local agent profiles: %s", exc)

    return sorted(names)


def _resolve_available_profile_display_name(profile: str) -> Optional[str]:
    display_name = _get_profile_display_name(profile)
    if display_name:
        return display_name

    profile_path = AGENT_CONTEXT_DIR / f"{profile}.md"
    if profile_path.exists():
        return _extract_profile_display_name(profile_path)

    try:
        builtin_store = resources.files("cli_agent_orchestrator.agent_store")
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("Failed to access built-in agent profiles: %s", exc)
        return None

    try:
        with resources.as_file(builtin_store / f"{profile}.md") as builtin_path:
            if builtin_path.exists():
                return _extract_profile_display_name(builtin_path)
    except FileNotFoundError:
        return None
    except Exception as exc:  # pragma: no cover - defensive fallback
        logger.warning("Failed to resolve built-in agent profile %s: %s", profile, exc)

    return None


def _list_available_agent_profile_options(
    profiles: Optional[List[str]] = None,
) -> List[Dict[str, Optional[str]]]:
    resolved_profiles = profiles if profiles is not None else _list_available_agent_profiles()
    options: List[Dict[str, Optional[str]]] = []

    for profile in resolved_profiles:
        display_name = _resolve_available_profile_display_name(profile)
        options.append(
            {
                "profile": profile,
                "display_name": display_name,
            }
        )

    return options


def _create_local_agent_profile(
    name: str,
    description: str,
    system_prompt: str,
    provider: Optional[str],
) -> Path:
    normalized_name = name.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", normalized_name):
        raise HTTPException(
            status_code=400,
            detail="Invalid profile name. Use letters, numbers, underscore, or hyphen.",
        )

    AGENT_CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    profile_path = AGENT_CONTEXT_DIR / f"{normalized_name}.md"

    if profile_path.exists():
        raise HTTPException(status_code=409, detail="Agent profile already exists")

    frontmatter_lines = [
        "---",
        f"name: {normalized_name}",
        f"description: {description.strip()}",
    ]
    if provider and provider.strip():
        frontmatter_lines.append(f"provider: {provider.strip()}")
    frontmatter_lines.append("---")

    content = "\n".join(frontmatter_lines) + "\n\n" + system_prompt.strip() + "\n"
    profile_path.write_text(content, encoding="utf-8")

    return profile_path


def _create_local_agent_profile_from_content(name: str, content: str) -> tuple[str, Path]:
    del name  # deprecated param kept for backward compatibility
    normalized_content = content.strip()
    if not normalized_content:
        raise HTTPException(status_code=400, detail="Profile content cannot be empty")

    metadata = _validate_profile_markdown_content(normalized_content)
    normalized_name = _validate_profile_name(str(metadata.get("name", "")))

    AGENT_CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    profile_path = AGENT_CONTEXT_DIR / f"{normalized_name}.md"

    if profile_path.exists():
        raise HTTPException(status_code=409, detail="Agent profile already exists")

    profile_path.write_text(normalized_content + "\n", encoding="utf-8")
    return normalized_name, profile_path


def _validate_profile_name(profile_name: str) -> str:
    normalized_name = profile_name.strip()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", normalized_name):
        raise HTTPException(
            status_code=400,
            detail="Invalid profile name. Use letters, numbers, underscore, or hyphen.",
        )
    return normalized_name


def _profile_file_path(profile_name: str) -> Path:
    normalized_name = _validate_profile_name(profile_name)
    return AGENT_CONTEXT_DIR / f"{normalized_name}.md"


def _list_local_agent_profile_files() -> List[Dict[str, Any]]:
    AGENT_CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    files: List[Dict[str, Any]] = []
    for file_path in sorted(AGENT_CONTEXT_DIR.glob("*.md")):
        profile_name = file_path.stem
        display_name = _resolve_profile_display_name(profile_name, file_path)
        files.append(
            {
                "file_name": file_path.name,
                "profile": profile_name,
                "file_path": str(file_path),
                "display_name": display_name,
            }
        )
    return files


_init_organization_db()


class LoginRequest(BaseModel):
    password: str = Field(min_length=1)


class AgentMessageRequest(BaseModel):
    message: str = Field(min_length=1)


class AgentTmuxInputRequest(BaseModel):
    message: str = Field(min_length=1)
    press_enter: bool = True


class WsTokenResponse(BaseModel):
    token: str
    expires_in: int


class ConsoleCreateShellTerminalRequest(BaseModel):
    working_directory: Optional[str] = None


class ProviderConfigDismissRequest(BaseModel):
    dismissed: bool = True


class OpenClawFeishuConfigRequest(BaseModel):
    enabled: bool = False
    domain: Literal["feishu", "lark"] = "feishu"
    connection_mode: Literal["websocket", "webhook"] = "websocket"
    app_id: Optional[str] = None
    app_secret: Optional[str] = None
    bot_name: Optional[str] = None
    verification_token: Optional[str] = None
    dm_policy: Literal["pairing", "allowlist", "open", "disabled"] = "pairing"
    account_id: str = "main"


class ProviderConfigApplyRequest(BaseModel):
    provider_id: str = Field(min_length=1)
    mode: Literal["account", "api"]
    api_base_url: Optional[str] = None
    api_key: Optional[str] = None
    default_model: Optional[str] = None
    compatibility: Optional[Literal["openai", "anthropic"]] = None
    feishu: Optional[OpenClawFeishuConfigRequest] = None


class ProviderCallbackRequest(BaseModel):
    callback_url: str = Field(min_length=1)


class ProviderConfigFileUpdateRequest(BaseModel):
    content: str


class InboxMessageRequest(BaseModel):
    message: str = Field(min_length=1)
    sender_id: Optional[str] = None


class OrgLinkRequest(BaseModel):
    worker_id: str = Field(min_length=1)
    leader_id: Optional[str] = None


class OrgCreateRequest(BaseModel):
    role_type: Literal["main", "worker"]
    agent_profile: str = Field(min_length=1)
    provider: Optional[str] = None
    leader_id: Optional[str] = None
    working_directory: Optional[str] = None
    team_workdir_mode: Optional[Literal["existing", "new"]] = None
    team_workdir_name: Optional[str] = None
    team_alias: Optional[str] = None
    agent_alias: Optional[str] = None


class OrgDisbandRequest(BaseModel):
    session_name: Optional[str] = None


class OrgLeaderUpdateRequest(BaseModel):
    agent_profile: str = Field(min_length=1)
    provider: Optional[str] = None
    team_alias: Optional[str] = None
    team_workdir_mode: Optional[Literal["existing", "new"]] = None
    team_workdir_name: Optional[str] = None
    working_directory: Optional[str] = None


class AgentProfileCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    content: Optional[str] = None
    provider: Optional[str] = None
    display_name: Optional[str] = None


class AgentProfileUpdateRequest(BaseModel):
    content: str = Field(min_length=1)
    display_name: Optional[str] = None


class ConsoleCreateScheduledTaskRequest(BaseModel):
    flow_content: Optional[str] = None
    flow_display_name: Optional[str] = None
    file_name: Optional[str] = None
    session_name: Optional[str] = None
    leader_id: Optional[str] = None


def _console_flow_root_dir() -> Path:
    flow_dir = AGENT_FLOW_DIR
    flow_dir.mkdir(parents=True, exist_ok=True)
    return flow_dir


def _validate_flow_session_name(session_name: str) -> str:
    normalized_session_name = (session_name or "").strip()
    if not normalized_session_name:
        raise HTTPException(status_code=400, detail="session_name cannot be empty")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", normalized_session_name):
        raise HTTPException(status_code=400, detail="Invalid session_name")
    return normalized_session_name


def _console_flow_dir(session_name: Optional[str] = None) -> Path:
    flow_root_dir = _console_flow_root_dir()
    if not session_name:
        return flow_root_dir
    normalized_session_name = _validate_flow_session_name(session_name)
    session_dir = flow_root_dir / normalized_session_name
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def _list_console_flow_files() -> List[Dict[str, Any]]:
    flow_dir = _console_flow_root_dir()
    files: List[Dict[str, Any]] = []
    for file_path in sorted(flow_dir.glob("**/*.md")):
        relative_name = file_path.relative_to(flow_dir).as_posix()
        flow_name = file_path.stem
        try:
            flow_name = _extract_flow_name_from_path(file_path)
        except HTTPException:
            pass
        files.append(
            {
                "file_name": relative_name,
                "flow_name": flow_name,
                "display_name": _get_flow_display_name(flow_name),
                "file_path": str(file_path),
            }
        )
    return files


def _normalize_console_flow_relative_name(file_name: str) -> str:
    normalized_name = (file_name or "").strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="file_name cannot be empty")

    if not normalized_name.endswith(".md"):
        normalized_name = f"{normalized_name}.md"

    relative_path = Path(normalized_name)
    if relative_path.is_absolute():
        raise HTTPException(status_code=400, detail="Invalid file_name")

    path_parts = relative_path.parts
    if any(part in {"", ".", ".."} for part in path_parts):
        raise HTTPException(status_code=400, detail="Invalid file_name")

    for part in path_parts:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", part):
            raise HTTPException(status_code=400, detail="Invalid file_name")

    return Path(*path_parts).as_posix()


def _parse_markdown_frontmatter(content: str, resource_name: str) -> Dict[str, Any]:
    try:
        post = frontmatter.loads(content)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {resource_name} markdown: {exc}")

    metadata = post.metadata if isinstance(post.metadata, dict) else {}
    if not metadata:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {resource_name} markdown: missing YAML frontmatter",
        )
    return metadata


def _validate_required_frontmatter_fields(
    metadata: Dict[str, Any],
    required_fields: List[str],
    resource_name: str,
) -> None:
    missing_fields = [field for field in required_fields if not str(metadata.get(field, "")).strip()]
    if missing_fields:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid {resource_name} markdown: missing required fields {', '.join(missing_fields)}",
        )


def _validate_profile_markdown_content(content: str) -> Dict[str, Any]:
    metadata = _parse_markdown_frontmatter(content, "agent profile")
    _validate_required_frontmatter_fields(metadata, ["name"], "agent profile")
    return metadata


def _extract_profile_display_name(profile_path: Path) -> Optional[str]:
    try:
        content = profile_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("Failed to read agent profile for display name: %s", exc)
        return None

    try:
        metadata = _parse_markdown_frontmatter(content, "agent profile")
    except HTTPException:
        return None

    display_name = str(metadata.get("name", "")).strip()
    return display_name or None


def _validate_flow_markdown_content(content: str) -> Dict[str, Any]:
    metadata = _parse_markdown_frontmatter(content, "flow")
    _validate_required_frontmatter_fields(metadata, ["name", "schedule", "agent_profile"], "flow")
    return metadata


def _validate_flow_name(flow_name: str) -> str:
    normalized_name = (flow_name or "").strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="Flow frontmatter.name cannot be empty")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", normalized_name):
        raise HTTPException(
            status_code=400,
            detail="Invalid flow name. Use letters, numbers, underscore, or hyphen.",
        )
    return normalized_name


def _resolve_console_flow_file(file_name: str) -> Path:
    flow_root_dir = _console_flow_root_dir().resolve()
    normalized_name = _normalize_console_flow_relative_name(file_name)
    flow_path = (flow_root_dir / normalized_name).resolve()

    try:
        flow_path.relative_to(flow_root_dir)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid file_name")

    if not flow_path.exists():
        raise HTTPException(status_code=404, detail=f"Flow file not found: {normalized_name}")

    return flow_path


def _extract_flow_name_from_content(flow_content: str) -> Optional[str]:
    content = (flow_content or "").strip()
    if not content:
        return None
    metadata = _validate_flow_markdown_content(content)
    return _validate_flow_name(str(metadata.get("name", "")))


def _extract_flow_name_from_path(flow_path: Path) -> str:
    content = flow_path.read_text(encoding="utf-8")
    extracted_name = _extract_flow_name_from_content(content)
    if not extracted_name:
        raise HTTPException(status_code=400, detail="Flow frontmatter.name cannot be empty")
    return extracted_name


def _is_duplicate_flow_name_error(response: Optional[requests.Response]) -> bool:
    if response is None:
        return False

    details: List[str] = []

    try:
        payload = response.json()
        if isinstance(payload, dict):
            detail = payload.get("detail")
            if isinstance(detail, str):
                details.append(detail)
            elif detail is not None:
                details.append(str(detail))
        else:
            details.append(str(payload))
    except ValueError:
        details.append(response.text or "")

    merged = "\n".join(details)
    return "UNIQUE constraint failed: flows.name" in merged


def _save_flow_content_to_file(
    flow_content: str,
    session_name: Optional[str] = None,
) -> Path:
    content = flow_content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Flow content cannot be empty")

    normalized_name = _extract_flow_name_from_content(content)
    if not normalized_name:
        raise HTTPException(status_code=400, detail="Flow frontmatter.name cannot be empty")

    flow_dir = _console_flow_dir(session_name=session_name)
    flow_path = flow_dir / f"{normalized_name}.md"
    flow_path.write_text(content + "\n", encoding="utf-8")
    return flow_path


def _overwrite_console_flow_file(flow_path: Path, flow_content: str) -> Path:
    content = flow_content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Flow content cannot be empty")

    flow_name = _extract_flow_name_from_content(content)
    if not flow_name:
        raise HTTPException(status_code=400, detail="Flow frontmatter.name cannot be empty")

    target_path = flow_path.parent / f"{flow_name}.md"
    if target_path.exists() and target_path.resolve() != flow_path.resolve():
        raise HTTPException(status_code=409, detail="Flow file name already exists")

    target_path.write_text(content + "\n", encoding="utf-8")
    if target_path.resolve() != flow_path.resolve() and flow_path.exists():
        flow_path.unlink()
    return target_path


def _set_flow_execution_session_name(flow_path: Path, session_name: Optional[str]) -> Path:
    normalized_session_name = (session_name or "").strip()
    if normalized_session_name:
        normalized_session_name = _validate_flow_session_name(normalized_session_name)

    with open(flow_path, "r", encoding="utf-8") as handle:
        post = frontmatter.load(handle)

    metadata = post.metadata if isinstance(post.metadata, dict) else {}
    if normalized_session_name:
        metadata["session_name"] = normalized_session_name
    else:
        metadata.pop("session_name", None)
    post.metadata = metadata

    flow_path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return flow_path


def _is_instant_task_status(status_value: Optional[str]) -> bool:
    normalized = (status_value or "").strip().lower()
    if not normalized:
        return False
    return normalized not in {
        "idle",
        "completed",
        "unknown",
        "stopped",
        "exited",
        "failed",
        "off_duty",
        "offline",
    }


def _normalize_flow_item(flow_item: Dict[str, Any]) -> Dict[str, Any]:
    flow_name = str(flow_item.get("name", ""))
    return {
        "name": flow_name,
        "display_name": _get_flow_display_name(flow_name),
        "file_path": str(flow_item.get("file_path", "")),
        "schedule": str(flow_item.get("schedule", "")),
        "agent_profile": str(flow_item.get("agent_profile", "")),
        "provider": str(flow_item.get("provider", "")),
        "script": str(flow_item.get("script", "")),
        "session_name": str(flow_item.get("session_name", "") or ""),
        "enabled": bool(flow_item.get("enabled", False)),
        "last_run": flow_item.get("last_run"),
        "next_run": flow_item.get("next_run"),
    }


async def _sync_bound_flow_session_name(flow_name: str) -> None:
    """Sync flow file frontmatter session_name from flow database value before execution."""
    try:
        flows_response = await asyncio.to_thread(_request_cao, "GET", "/flows")
        flow_items = await asyncio.to_thread(_response_json_or_text, flows_response)
        if not isinstance(flow_items, list):
            return

        matched_file_path: Optional[str] = None
        matched_session_name: Optional[str] = None
        for item in flow_items:
            if not isinstance(item, dict):
                continue
            if str(item.get("name", "")) != flow_name:
                continue
            candidate = str(item.get("file_path", "") or "").strip()
            if candidate:
                matched_file_path = candidate
            session_candidate = str(item.get("session_name", "") or "").strip()
            if session_candidate:
                matched_session_name = session_candidate
            break

        if not matched_file_path or not matched_session_name:
            return

        await asyncio.to_thread(
            _set_flow_execution_session_name,
            Path(matched_file_path),
            matched_session_name,
        )
    except Exception as exc:
        logger.warning(
            "Failed to sync bound flow session_name before run for flow=%s: %s",
            flow_name,
            exc,
        )


def _cleanup_expired_sessions() -> None:
    now = time.time()
    expired_tokens = [token for token, expires_at in _sessions.items() if expires_at <= now]
    for token in expired_tokens:
        _sessions.pop(token, None)


def _cleanup_expired_ws_tokens() -> None:
    now = time.time()
    expired_tokens = [token for token, expires_at in _ws_tokens.items() if expires_at <= now]
    for token in expired_tokens:
        _ws_tokens.pop(token, None)


def _session_expires_at(token: str) -> Optional[float]:
    _cleanup_expired_sessions()
    return _sessions.get(token)


def _create_ws_token() -> str:
    _cleanup_expired_ws_tokens()
    token = secrets.token_urlsafe(24)
    _ws_tokens[token] = time.time() + WS_TOKEN_TTL_SECONDS
    return token


def _consume_ws_token(token: str) -> bool:
    _cleanup_expired_ws_tokens()
    expires_at = _ws_tokens.pop(token, None)
    return expires_at is not None and expires_at > time.time()


def _is_authenticated(request: Request) -> bool:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return False
    return _session_expires_at(token) is not None


def _create_session() -> str:
    _cleanup_expired_sessions()
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time() + SESSION_TTL_SECONDS
    return token


def _build_cookie_response(payload: Dict[str, Any], token: Optional[str]) -> JSONResponse:
    response = JSONResponse(payload)
    if token is None:
        response.delete_cookie(SESSION_COOKIE_NAME, samesite="lax")
        return response

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
    )
    return response


def _request_cao(
    method: str,
    path: str,
    params: Optional[Dict[str, str]] = None,
    json_body: Optional[Dict[str, Any]] = None,
) -> requests.Response:
    url = f"{CAO_SERVER_URL}{path}"
    response = requests.request(method=method, url=url, params=params, json=json_body, timeout=30)
    response.raise_for_status()
    return response


def _response_json_or_text(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _run_provider_command(
    args: List[str],
    *,
    input_text: Optional[str] = None,
    timeout: int = 25,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _probe_cli_subcommand(command: str, subcommand: str) -> bool:
    if shutil.which(command) is None:
        return False

    try:
        result = _run_provider_command([command, subcommand, "--help"], timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False

    output = "\n".join(part for part in [result.stdout, result.stderr] if part).strip().lower()
    if not output:
        return result.returncode == 0

    unsupported_markers = (
        "unknown command",
        "unknown arguments",
        "no such command",
        "unrecognized",
        "invalid choice",
        "unexpected argument",
        "did you mean",
        "command not found",
    )
    if any(marker in output for marker in unsupported_markers):
        return False

    command_pattern = re.compile(
        rf"usage:\s*{re.escape(command.lower())}(?:\|[^\s]+)?\s+{re.escape(subcommand.lower())}\b"
    )
    if command_pattern.search(output):
        return True

    return f" {subcommand.lower()} " in f" {output} " and result.returncode == 0


def _build_provider_action_metadata(item: Dict[str, Any]) -> Dict[str, Any]:
    command = str(item.get("command") or "").strip()
    supports_account_login = bool(item.get("supports_account_login"))
    console_command = item.get("console_command") if supports_account_login else None
    login_command = item.get("login_command") if supports_account_login else None
    logout_command = item.get("logout_command") if supports_account_login else None
    login_via_console = bool(item.get("login_via_console"))
    logout_via_console = bool(item.get("logout_via_console"))
    logout_supported_override = item.get("logout_supported_override")

    login_supported = False
    logout_supported = False
    if supports_account_login and command:
        if login_via_console:
            login_supported = bool(console_command) and bool(login_command)
        else:
            login_supported = bool(login_command)

        if logout_via_console:
            logout_supported = bool(console_command) and bool(logout_command)
        else:
            logout_supported = bool(logout_command) and _probe_cli_subcommand(command, "logout")

    if isinstance(logout_supported_override, bool):
        logout_supported = logout_supported_override and bool(logout_command)

    return {
        "console_command": console_command,
        "login_command": login_command,
        "logout_command": logout_command if logout_supported else None,
        "login_via_console": login_via_console,
        "logout_via_console": logout_via_console,
        "login_supported": login_supported,
        "logout_supported": logout_supported,
    }


def _provider_settings_path(provider_id: str) -> Optional[Path]:
    mapping = {
        "claude_code": Path.home() / ".claude" / "settings.json",
        "codex": Path.home() / ".codex" / "config.toml",
        "openclaw": Path.home() / ".openclaw" / "openclaw.json",
        "codebuddy": Path.home() / ".codebuddy" / "settings.json",
    }
    return mapping.get(provider_id)


def _read_json_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_json_file(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def _parse_toml_file(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def _toml_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _upsert_top_level_toml_key(content: str, key: str, value: str) -> str:
    pattern = re.compile(rf"(?m)^{re.escape(key)}\s*=\s*.*$")
    replacement = f"{key} = {value}"
    if pattern.search(content):
        return pattern.sub(replacement, content, count=1)
    suffix = "\n" if content and not content.endswith("\n") else ""
    return f"{content}{suffix}{replacement}\n"


def _upsert_toml_section(content: str, section_name: str, values: Dict[str, str]) -> str:
    lines = content.splitlines()
    section_header = f"[{section_name}]"
    start_index = -1
    end_index = len(lines)

    for index, line in enumerate(lines):
        if line.strip() == section_header:
            start_index = index
            break

    if start_index >= 0:
        for index in range(start_index + 1, len(lines)):
            if lines[index].startswith("[") and lines[index].endswith("]"):
                end_index = index
                break
        body = lines[start_index + 1 : end_index]
    else:
        body = []

    for key, value in values.items():
        updated = False
        pattern = re.compile(rf"^{re.escape(key)}\s*=")
        for index, line in enumerate(body):
            if pattern.match(line.strip()):
                body[index] = f"{key} = {value}"
                updated = True
                break
        if not updated:
            body.append(f"{key} = {value}")

    replacement_lines = [section_header, *body]
    if start_index >= 0:
        lines = [*lines[:start_index], *replacement_lines, *lines[end_index:]]
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(replacement_lines)

    rendered = "\n".join(lines).rstrip()
    return f"{rendered}\n"


def _write_codex_config(default_model: str, api_base_url: str) -> Path:
    path = Path.home() / ".codex" / "config.toml"
    content = path.read_text(encoding="utf-8") if path.exists() else ""
    content = _upsert_top_level_toml_key(content, "model", _toml_string(default_model))
    content = _upsert_top_level_toml_key(content, "model_provider", _toml_string("api"))
    content = _upsert_toml_section(
        content,
        "model_providers.api",
        {
            "name": _toml_string("IDE API"),
            "base_url": _toml_string(api_base_url),
            "api_key_env": _toml_string("OPENAI_API_KEY"),
        },
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _write_codex_auth(api_key: str) -> Path:
    path = Path.home() / ".codex" / "auth.json"
    payload = _read_json_file(path)
    payload["auth_mode"] = "apikey"
    payload["OPENAI_API_KEY"] = api_key
    payload.pop("API_KEY", None)

    env_payload = payload.get("ENV")
    env_data = dict(env_payload) if isinstance(env_payload, dict) else {}
    env_data["OPENAI_API_KEY"] = api_key
    env_data.pop("API_KEY", None)
    payload["ENV"] = env_data

    _write_json_file(path, payload)
    return path


def _write_claude_settings(api_base_url: str, api_key: str, default_model: str) -> Path:
    path = Path.home() / ".claude" / "settings.json"
    payload = _read_json_file(path)
    env_payload = payload.get("env")
    env_data = dict(env_payload) if isinstance(env_payload, dict) else {}
    env_data["ANTHROPIC_BASE_URL"] = api_base_url
    env_data["ANTHROPIC_API_KEY"] = api_key
    env_data.pop("ANTHROPIC_AUTH_TOKEN", None)
    env_data.pop("ANTHROPIC_API_TOKEN", None)
    env_data["ANTHROPIC_MODEL"] = default_model
    payload["env"] = env_data
    _write_json_file(path, payload)
    return path


def _write_openclaw_api_settings(
    api_base_url: str,
    default_model: str,
    compatibility: str,
) -> Path:
    path = Path.home() / ".openclaw" / "openclaw.json"
    payload = _read_json_file(path)

    models_payload = payload.get("models")
    models_data = dict(models_payload) if isinstance(models_payload, dict) else {}
    providers_payload = models_data.get("providers")
    providers_data = dict(providers_payload) if isinstance(providers_payload, dict) else {}

    auth_profiles = payload.get("auth", {}).get("profiles")
    provider_key = None
    if isinstance(auth_profiles, dict):
        for profile in auth_profiles.values():
            if isinstance(profile, dict) and isinstance(profile.get("provider"), str):
                provider_key = str(profile["provider"]).strip()
                if provider_key:
                    break

    if not provider_key and providers_data:
        provider_key = next(iter(providers_data.keys()))
    if not provider_key:
        provider_key = "api"

    provider_payload = providers_data.get(provider_key)
    provider_data = dict(provider_payload) if isinstance(provider_payload, dict) else {}
    provider_data["baseUrl"] = api_base_url
    provider_data["api"] = "anthropic-messages" if compatibility == "anthropic" else "openai-completions"
    providers_data[provider_key] = provider_data
    models_data["providers"] = providers_data
    payload["models"] = models_data

    agents_payload = payload.get("agents")
    agents_data = dict(agents_payload) if isinstance(agents_payload, dict) else {}
    defaults_payload = agents_data.get("defaults")
    defaults_data = dict(defaults_payload) if isinstance(defaults_payload, dict) else {}
    model_payload = defaults_data.get("model")
    model_data = dict(model_payload) if isinstance(model_payload, dict) else {}
    model_data["primary"] = f"{provider_key}/{default_model}"
    defaults_data["model"] = model_data
    agents_data["defaults"] = defaults_data
    payload["agents"] = agents_data

    _write_json_file(path, payload)
    return path


def _read_provider_config_file(provider_id: str) -> Dict[str, Any]:
    path = _provider_settings_path(provider_id)
    if path is None:
                raise HTTPException(status_code=404, detail=f"{provider_id} does not expose a config file")

    if path.exists():
        content = path.read_text(encoding="utf-8")
    elif provider_id == "openclaw":
        content = "{}\n"
    else:
        raise HTTPException(status_code=404, detail=f"Config file not found for {provider_id}")

    return {
        "provider_id": provider_id,
        "path": str(path),
        "content": content,
    }


def _restart_openclaw_gateway() -> Dict[str, Any]:
    restart_result = _run_provider_command(["openclaw", "gateway", "restart"], timeout=30)
    if restart_result.returncode == 0:
        return {
            "command": "openclaw gateway restart",
            "stdout": (restart_result.stdout or "").strip(),
            "stderr": (restart_result.stderr or "").strip(),
        }

    start_result = _run_provider_command(["openclaw", "gateway", "start"], timeout=30)
    if start_result.returncode == 0:
        return {
            "command": "openclaw gateway start",
            "stdout": (start_result.stdout or "").strip(),
            "stderr": (start_result.stderr or "").strip(),
        }

    detail = (
        start_result.stderr
        or start_result.stdout
        or restart_result.stderr
        or restart_result.stdout
        or "Failed to restart OpenClaw gateway"
    ).strip()
    raise HTTPException(status_code=500, detail=detail)


def _save_provider_config_file(provider_id: str, content: str) -> Dict[str, Any]:
    path = _provider_settings_path(provider_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"{provider_id} does not expose a config file")

    rendered = content
    if provider_id == "openclaw":
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid OpenClaw config JSON: {exc}")
        rendered = json.dumps(parsed, indent=2, ensure_ascii=True)
        if not rendered.endswith("\n"):
            rendered += "\n"

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")

    result: Dict[str, Any] = {
        "provider_id": provider_id,
        "path": str(path),
        "content": rendered,
    }
    if provider_id == "openclaw":
        result["gateway"] = _restart_openclaw_gateway()
    return result


def _merge_saved_settings(runtime_settings: Dict[str, Any], detected_settings: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(detected_settings)
    for key, value in runtime_settings.items():
        if value is None:
            continue
        if key == "feishu" and isinstance(value, dict):
            current = merged.get("feishu")
            current_data = dict(current) if isinstance(current, dict) else {}
            current_data.update(value)
            merged["feishu"] = current_data
            continue
        merged[key] = value
    return merged


def _read_claude_saved_settings() -> Dict[str, Any]:
    settings_path = _provider_settings_path("claude_code")
    payload = _read_json_file(settings_path) if settings_path else {}
    env_payload = payload.get("env")
    env_data = dict(env_payload) if isinstance(env_payload, dict) else {}

    api_base_url = str(env_data.get("ANTHROPIC_BASE_URL") or "").strip() or None
    api_key = str(
        env_data.get("ANTHROPIC_API_KEY")
        or env_data.get("ANTHROPIC_AUTH_TOKEN")
        or env_data.get("ANTHROPIC_API_TOKEN")
        or ""
    ).strip() or None
    default_model = str(env_data.get("ANTHROPIC_MODEL") or "").strip() or None

    if not any([api_base_url, api_key, default_model]):
        return {}

    return {
        "mode": "api",
        "api_base_url": api_base_url,
        "api_key": api_key,
        "default_model": default_model,
    }


def _read_codex_saved_settings() -> Dict[str, Any]:
    settings_path = _provider_settings_path("codex")
    payload = _parse_toml_file(settings_path) if settings_path else {}
    provider_name = str(payload.get("model_provider") or "").strip() or None
    model_providers = payload.get("model_providers")
    providers_data = dict(model_providers) if isinstance(model_providers, dict) else {}
    selected_provider = providers_data.get(provider_name or "")
    selected_data = dict(selected_provider) if isinstance(selected_provider, dict) else {}
    api_key_env = str(selected_data.get("api_key_env") or "").strip()

    settings: Dict[str, Any] = {}
    if provider_name or payload.get("model") or selected_data.get("base_url"):
        settings["mode"] = "api"
    if selected_data.get("base_url"):
        settings["api_base_url"] = str(selected_data.get("base_url")).strip()
    if payload.get("model"):
        settings["default_model"] = str(payload.get("model")).strip()
    if api_key_env and os.getenv(api_key_env):
        settings["api_key"] = str(os.getenv(api_key_env) or "").strip()

    auth_path = Path.home() / ".codex" / "auth.json"
    auth_payload = _read_json_file(auth_path)
    if isinstance(auth_payload, dict):
        auth_mode = str(auth_payload.get("auth_mode") or "").strip().lower()
        auth_env_payload = auth_payload.get("ENV")
        auth_env_data = dict(auth_env_payload) if isinstance(auth_env_payload, dict) else {}
        if auth_mode == "apikey":
            settings["mode"] = "api"
            if api_key_env and not settings.get("api_key"):
                auth_key = str(auth_payload.get(api_key_env) or auth_env_data.get(api_key_env) or "").strip()
                if auth_key:
                    settings["api_key"] = auth_key
            if not settings.get("api_key"):
                for candidate in ["API_KEY", "OPENAI_API_KEY", "OPENROUTER_API_KEY", "ZHIPU_API_KEY"]:
                    auth_key = str(auth_payload.get(candidate) or auth_env_data.get(candidate) or "").strip()
                    if auth_key:
                        settings["api_key"] = auth_key
                        break
    return settings


def _read_openclaw_saved_settings() -> Dict[str, Any]:
    config_path = _provider_settings_path("openclaw")
    payload = _read_json_file(config_path) if config_path else {}
    if not payload:
        return {}

    settings: Dict[str, Any] = {"mode": "api"}

    auth_profiles = payload.get("auth", {}).get("profiles")
    provider_key = None
    if isinstance(auth_profiles, dict):
        for profile in auth_profiles.values():
            if isinstance(profile, dict) and isinstance(profile.get("provider"), str):
                provider_key = str(profile["provider"]).strip()
                if provider_key:
                    break

    models_payload = payload.get("models")
    models_data = dict(models_payload) if isinstance(models_payload, dict) else {}
    providers_payload = models_data.get("providers")
    providers_data = dict(providers_payload) if isinstance(providers_payload, dict) else {}
    if not provider_key and providers_data:
        provider_key = next(iter(providers_data.keys()))
    provider_payload = providers_data.get(provider_key or "")
    provider_data = dict(provider_payload) if isinstance(provider_payload, dict) else {}
    base_url = str(provider_data.get("baseUrl") or provider_data.get("base_url") or "").strip()
    if base_url:
        settings["api_base_url"] = base_url

    api_shape = str(provider_data.get("api") or "").strip().lower()
    if api_shape.startswith("anthropic"):
        settings["compatibility"] = "anthropic"
    elif provider_data:
        settings["compatibility"] = "openai"

    agents_payload = payload.get("agents")
    agents_data = dict(agents_payload) if isinstance(agents_payload, dict) else {}
    defaults_payload = agents_data.get("defaults")
    defaults_data = dict(defaults_payload) if isinstance(defaults_payload, dict) else {}
    model_payload = defaults_data.get("model")
    model_data = dict(model_payload) if isinstance(model_payload, dict) else {}
    primary_model = str(model_data.get("primary") or "").strip()
    if primary_model:
        settings["default_model"] = primary_model.split("/", 1)[1] if "/" in primary_model else primary_model

    channels_payload = payload.get("channels")
    channels_data = dict(channels_payload) if isinstance(channels_payload, dict) else {}
    feishu_payload = channels_data.get("feishu")
    feishu_data = dict(feishu_payload) if isinstance(feishu_payload, dict) else {}
    if feishu_data:
        account_id = str(feishu_data.get("defaultAccount") or "main").strip() or "main"
        accounts_payload = feishu_data.get("accounts")
        accounts_data = dict(accounts_payload) if isinstance(accounts_payload, dict) else {}
        account_payload = accounts_data.get(account_id)
        account_data = dict(account_payload) if isinstance(account_payload, dict) else {}

        settings["feishu"] = {
            "enabled": bool(feishu_data.get("enabled")),
            "domain": str(feishu_data.get("domain") or "feishu").strip() or "feishu",
            "connection_mode": str(feishu_data.get("connectionMode") or "websocket").strip() or "websocket",
            "app_id": str(account_data.get("appId") or feishu_data.get("appId") or "").strip(),
            "app_secret": str(account_data.get("appSecret") or feishu_data.get("appSecret") or "").strip(),
            "bot_name": str(account_data.get("botName") or feishu_data.get("botName") or "").strip(),
            "verification_token": str(feishu_data.get("verificationToken") or "").strip() or None,
            "dm_policy": str(
                feishu_data.get("dmPolicy")
                or feishu_data.get("groupPolicy")
                or "pairing"
            ).strip()
            or "pairing",
            "account_id": account_id,
        }

    return settings


def _get_provider_saved_settings(provider_id: str) -> Dict[str, Any]:
    runtime_settings = get_provider_runtime_settings(provider_id)
    readers = {
        "claude_code": _read_claude_saved_settings,
        "codex": _read_codex_saved_settings,
        "openclaw": _read_openclaw_saved_settings,
    }
    reader = readers.get(provider_id)
    detected_settings = reader() if reader else {}
    return _merge_saved_settings(runtime_settings, detected_settings)


def _merge_openclaw_feishu_config(
    *,
    domain: str,
    connection_mode: str,
    app_id: str,
    app_secret: str,
    bot_name: str,
    verification_token: Optional[str],
    dm_policy: str,
    account_id: str,
) -> Path:
    path = Path.home() / ".openclaw" / "openclaw.json"
    payload = _read_json_file(path)

    channels = payload.get("channels")
    channels_data = dict(channels) if isinstance(channels, dict) else {}
    feishu = channels_data.get("feishu")
    feishu_data = dict(feishu) if isinstance(feishu, dict) else {}
    accounts = feishu_data.get("accounts")
    accounts_data = dict(accounts) if isinstance(accounts, dict) else {}

    feishu_data["enabled"] = True
    feishu_data["domain"] = domain
    feishu_data["connectionMode"] = connection_mode
    feishu_data["dmPolicy"] = dm_policy
    feishu_data["defaultAccount"] = account_id

    account_payload = accounts_data.get(account_id)
    account_data = dict(account_payload) if isinstance(account_payload, dict) else {}
    account_data["appId"] = app_id
    account_data["appSecret"] = app_secret
    if bot_name:
        account_data["botName"] = bot_name
    accounts_data[account_id] = account_data
    feishu_data["accounts"] = accounts_data

    if connection_mode == "webhook":
        feishu_data["verificationToken"] = verification_token or ""
    else:
        feishu_data.pop("verificationToken", None)

    channels_data["feishu"] = feishu_data
    payload["channels"] = channels_data
    _write_json_file(path, payload)
    return path


def _detect_claude_status() -> Dict[str, Any]:
    installed = shutil.which("claude") is not None
    runtime_settings = _get_provider_saved_settings("claude_code")
    details = ""
    configured = False
    detected_mode = runtime_settings.get("mode")

    if installed:
        result = _run_provider_command(["claude", "auth", "status"])
        stdout = (result.stdout or "").strip()
        if stdout:
            details = stdout
        try:
            payload = json.loads(stdout) if stdout else {}
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict) and payload.get("loggedIn") is True:
            configured = True
            detected_mode = detected_mode or "account"
            details = payload.get("authMethod") or details

    if runtime_settings.get("mode") == "api" and runtime_settings.get("api_key"):
        configured = True
        detected_mode = "api"
        details = runtime_settings.get("default_model") or runtime_settings.get("api_base_url") or details

    return {
        "installed": installed,
        "configured": configured,
        "detected_mode": detected_mode,
        "details": details,
        "settings_path": str(_provider_settings_path("claude_code")) if _provider_settings_path("claude_code") else None,
    }


def _detect_codex_status() -> Dict[str, Any]:
    installed = shutil.which("codex") is not None
    runtime_settings = _get_provider_saved_settings("codex")
    details = ""
    configured = False
    detected_mode = runtime_settings.get("mode")

    if installed:
        result = _run_provider_command(["codex", "login", "status"])
        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        details = stdout or stderr
        if result.returncode == 0 and stdout:
            configured = True
            detected_mode = "api" if "api key" in stdout.lower() else (detected_mode or "account")

    if runtime_settings.get("mode") == "api" and runtime_settings.get("api_key"):
        configured = True
        detected_mode = "api"
        details = runtime_settings.get("default_model") or details

    return {
        "installed": installed,
        "configured": configured,
        "detected_mode": detected_mode,
        "details": details,
        "settings_path": str(_provider_settings_path("codex")) if _provider_settings_path("codex") else None,
    }


def _detect_kiro_status() -> Dict[str, Any]:
    installed = shutil.which("kiro-cli") is not None
    details = ""
    configured = False
    if installed:
        result = _run_provider_command(["kiro-cli", "whoami", "--format", "json"])
        stdout = (result.stdout or "").strip()
        details = stdout or (result.stderr or "").strip()
        try:
            payload = json.loads(stdout) if stdout else {}
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict) and payload.get("accountType"):
            configured = True
            details = str(payload.get("accountType"))
    return {
        "installed": installed,
        "configured": configured,
        "detected_mode": "account" if configured else None,
        "details": details,
        "settings_path": None,
    }


def _detect_qoder_status() -> Dict[str, Any]:
    installed = shutil.which("qodercli") is not None
    details = ""
    configured = False
    if installed:
        result = _run_provider_command(["qodercli", "status"])
        stdout = (result.stdout or "").strip()
        details = stdout or (result.stderr or "").strip()
        configured = result.returncode == 0 and "Username:" in stdout
    return {
        "installed": installed,
        "configured": configured,
        "detected_mode": "account" if configured else None,
        "details": details,
        "settings_path": None,
    }


def _detect_copilot_status() -> Dict[str, Any]:
    installed = shutil.which("copilot") is not None
    runtime_settings = get_provider_runtime_settings("copilot")
    env_tokens = [
        os.getenv("COPILOT_GITHUB_TOKEN"),
        os.getenv("GH_TOKEN"),
        os.getenv("GITHUB_TOKEN"),
    ]
    config_dir = Path.home() / ".copilot"
    configured = any(bool(str(token or "").strip()) for token in env_tokens)
    if not configured and config_dir.exists():
        configured = any(item.is_file() and item.name != "mcp-config.json" for item in config_dir.iterdir())
    if runtime_settings.get("login_completed_at"):
        configured = True
    details = "device-flow / browser OAuth"
    return {
        "installed": installed,
        "configured": configured,
        "detected_mode": "account" if configured else None,
        "details": details,
        "settings_path": str(config_dir) if config_dir.exists() else None,
    }


def _detect_codebuddy_status() -> Dict[str, Any]:
    installed = shutil.which("codebuddy") is not None
    runtime_settings = get_provider_runtime_settings("codebuddy")
    settings_path = _provider_settings_path("codebuddy")
    configured = bool(runtime_settings.get("login_completed_at"))
    details = ""
    if installed:
        try:
            result = _run_provider_command(["codebuddy", "config", "get", "model"])
        except (OSError, subprocess.TimeoutExpired) as exc:
            logger.info("CodeBuddy status probe failed; treating as unconfigured: %s", exc)
        else:
            stdout = (result.stdout or "").strip()
            stderr = (result.stderr or "").strip()
            details = stdout or stderr
            if result.returncode == 0 and stdout:
                configured = True
                details = f"model={stdout.splitlines()[0]}"
    return {
        "installed": installed,
        "configured": configured,
        "detected_mode": "account" if configured else None,
        "details": details,
        "settings_path": str(settings_path) if settings_path else None,
    }


def _detect_openclaw_status() -> Dict[str, Any]:
    installed = shutil.which("openclaw") is not None
    runtime_settings = _get_provider_saved_settings("openclaw")
    config_path = _provider_settings_path("openclaw")
    payload = _read_json_file(config_path) if config_path else {}
    configured = bool(runtime_settings.get("api_key"))
    details = ""
    if isinstance(payload, dict):
        channels = payload.get("channels")
        feishu_configured = isinstance(channels, dict) and isinstance(channels.get("feishu"), dict)
        if feishu_configured:
            details = "Feishu 已配置"
        models = payload.get("models")
        if isinstance(models, dict) and models.get("providers"):
            configured = True
    if runtime_settings.get("default_model"):
        configured = True
        details = runtime_settings.get("compatibility") or runtime_settings.get("default_model") or details
    return {
        "installed": installed,
        "configured": configured,
        "detected_mode": "api" if configured else None,
        "details": details,
        "settings_path": str(config_path) if config_path else None,
    }


def _detect_provider_status(provider_id: str) -> Dict[str, Any]:
    detectors = {
        "claude_code": _detect_claude_status,
        "codex": _detect_codex_status,
        "openclaw": _detect_openclaw_status,
        "copilot": _detect_copilot_status,
        "qoder_cli": _detect_qoder_status,
        "kiro_cli": _detect_kiro_status,
        "codebuddy": _detect_codebuddy_status,
    }
    detector = detectors.get(provider_id)
    if detector is None:
        return {
            "installed": False,
            "configured": False,
            "detected_mode": None,
            "details": "Unsupported provider",
            "settings_path": None,
        }
    return detector()


def _build_provider_guide_item(item: Dict[str, Any]) -> Dict[str, Any]:
    provider_id = str(item["id"])
    status_payload = _detect_provider_status(provider_id)
    provider_settings = _get_provider_saved_settings(provider_id)
    return {
        **item,
        **_build_provider_action_metadata(item),
        "status": status_payload,
        "saved_settings": provider_settings,
    }


def _build_provider_guide_summary() -> Dict[str, Any]:
    runtime_config = load_provider_runtime_config()
    onboarding = runtime_config.get("onboarding", {})
    dismissed = bool(onboarding.get("dismissed"))
    completed_at = onboarding.get("completed_at")
    provider_summaries: List[Dict[str, Any]] = []
    any_configured = False

    for item in CONTROL_PANEL_PROVIDER_GUIDES:
        provider_summary = _build_provider_guide_item(item)
        status_payload = provider_summary["status"]
        configured = bool(status_payload.get("configured"))
        any_configured = any_configured or configured
        provider_summaries.append(provider_summary)

    should_show_guide = not dismissed and not completed_at and not any_configured
    return {
        "should_show_guide": should_show_guide,
        "onboarding": onboarding,
        "providers": provider_summaries,
    }


def _build_single_provider_guide(provider_id: str) -> Dict[str, Any]:
    provider_meta = next((item for item in CONTROL_PANEL_PROVIDER_GUIDES if item["id"] == provider_id), None)
    if provider_meta is None:
        raise HTTPException(status_code=404, detail=f"Unsupported provider: {provider_id}")
    return _build_provider_guide_item(provider_meta)


def _get_terminal_tmux_target(terminal_id: str) -> tuple[str, str]:
    resolved_terminal_id = _resolve_terminal_id_alias(terminal_id)
    terminal_response = _request_cao("GET", f"/terminals/{resolved_terminal_id}")
    terminal_data = _response_json_or_text(terminal_response)
    if not isinstance(terminal_data, dict):
        raise HTTPException(status_code=502, detail="Invalid terminal metadata from cao-server")

    tmux_session = str(
        terminal_data.get("tmux_session") or terminal_data.get("session_name") or ""
    ).strip()
    tmux_window = str(terminal_data.get("tmux_window") or terminal_data.get("name") or "").strip()

    if tmux_session and tmux_window:
        return tmux_session, tmux_window

    if tmux_session:
        try:
            session_terms_resp = _request_cao("GET", f"/sessions/{tmux_session}/terminals")
            session_terms_data = _response_json_or_text(session_terms_resp)
            if isinstance(session_terms_data, list):
                for item in session_terms_data:
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("id", "")).strip() != terminal_id:
                        continue
                    candidate_window = str(item.get("tmux_window") or item.get("name") or "").strip()
                    if candidate_window:
                        return tmux_session, candidate_window
        except Exception as exc:
            logger.warning("Failed to resolve tmux window from session terminal list: %s", exc)

    if not tmux_session or not tmux_window:
        raise HTTPException(
            status_code=404,
            detail=f"Terminal {resolved_terminal_id} has no tmux target",
        )

    return tmux_session, tmux_window


def _get_terminals_from_sessions() -> list[Dict[str, Any]]:
    sessions_response = _request_cao("GET", "/sessions")
    sessions_data = _response_json_or_text(sessions_response)
    if not isinstance(sessions_data, list):
        return []

    terminals: list[Dict[str, Any]] = []
    for session in sessions_data:
        session_name = session.get("name")
        if not session_name:
            continue
        try:
            terminals_response = _request_cao("GET", f"/sessions/{session_name}/terminals")
            session_terminals = _response_json_or_text(terminals_response)
            if isinstance(session_terminals, list):
                terminals.extend(session_terminals)
        except Exception as exc:
            logger.warning("Failed to fetch terminals for session %s: %s", session_name, exc)

    enriched_terminals: list[Dict[str, Any]] = []
    for terminal in terminals:
        terminal_id = terminal.get("id")
        terminal_info = dict(terminal)
        if terminal_id:
            try:
                details_response = _request_cao("GET", f"/terminals/{terminal_id}")
                details_data = _response_json_or_text(details_response)
                if isinstance(details_data, dict):
                    terminal_info.update(details_data)
            except Exception as exc:
                logger.warning("Failed to fetch terminal details %s: %s", terminal_id, exc)

        profile = str(terminal_info.get("agent_profile", "")).lower()
        terminal_info["is_main"] = "supervisor" in profile
        enriched_terminals.append(terminal_info)

    return enriched_terminals


def _list_live_sessions() -> set[str]:
    sessions_response = _request_cao("GET", "/sessions")
    sessions_data = _response_json_or_text(sessions_response)
    if not isinstance(sessions_data, list):
        return set()
    return {
        str(item.get("name", "")).strip()
        for item in sessions_data
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    }


def _find_live_leader_terminal(
    session_name: str, expected_leader_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    session_terminals_response = _request_cao("GET", f"/sessions/{session_name}/terminals")
    session_terminals_data = _response_json_or_text(session_terminals_response)
    if not isinstance(session_terminals_data, list):
        return None

    fallback_main: Optional[Dict[str, Any]] = None
    fallback_any: Optional[Dict[str, Any]] = None
    for terminal in session_terminals_data:
        if not isinstance(terminal, dict):
            continue
        terminal_id = str(terminal.get("id", "")).strip()
        if not terminal_id:
            continue
        profile = str(terminal.get("agent_profile", "")).lower()
        if expected_leader_id and terminal_id == expected_leader_id:
            return terminal
        if "supervisor" in profile:
            return terminal
        if terminal.get("is_main") and not fallback_main:
            fallback_main = terminal
        if not fallback_any:
            fallback_any = terminal
    return fallback_main or fallback_any


def _default_restore_session_name(leader_id: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]", "-", leader_id.strip())
    normalized = normalized.strip("-.")
    if not normalized:
        normalized = uuid.uuid4().hex[:8]
    return _validate_flow_session_name(f"cao-team-{normalized[:20]}")


def _ensure_team_leader_online(leader_id: str) -> Dict[str, Any]:
    normalized_leader_id = leader_id.strip()
    if not normalized_leader_id:
        raise HTTPException(status_code=400, detail="leader_id cannot be empty")

    team_ids = _list_teams()
    if normalized_leader_id not in team_ids:
        raise HTTPException(status_code=404, detail=f"Team not found for leader_id: {normalized_leader_id}")

    runtime = _get_team_runtime(normalized_leader_id) or {}
    runtime_terminal_id = str(runtime.get("terminal_id") or "").strip()
    runtime_session_name = str(runtime.get("session_name") or "").strip()
    runtime_provider = str(runtime.get("provider") or "").strip()
    runtime_profile = str(runtime.get("agent_profile") or "").strip()
    runtime_workdir = str(runtime.get("working_directory") or "").strip()

    source_terminal_id = runtime_terminal_id or normalized_leader_id
    source_terminal = _get_terminal_db_metadata(source_terminal_id)

    provider = runtime_provider or (source_terminal or {}).get("provider") or DEFAULT_PROVIDER
    agent_profile = runtime_profile or (source_terminal or {}).get("agent_profile") or "code_supervisor"
    session_name = runtime_session_name or (source_terminal or {}).get("tmux_session") or _default_restore_session_name(normalized_leader_id)
    session_name = _validate_flow_session_name(session_name)

    working_directory = runtime_workdir
    if not working_directory:
        team_workdirs = _list_team_working_directories()
        working_directory = str(team_workdirs.get(normalized_leader_id) or "").strip()

    live_sessions = _list_live_sessions()
    if session_name in live_sessions:
        live_terminal = _find_live_leader_terminal(
            session_name, runtime_terminal_id or normalized_leader_id
        )
        if live_terminal:
            live_terminal_id = str(live_terminal.get("id") or "").strip()
            if live_terminal_id:
                if normalized_leader_id != live_terminal_id:
                    _rekey_leader_id(normalized_leader_id, live_terminal_id)
                    normalized_leader_id = live_terminal_id
                _upsert_team_runtime(
                    normalized_leader_id,
                    terminal_id=live_terminal_id,
                    session_name=session_name,
                    provider=str(live_terminal.get("provider") or provider),
                    agent_profile=str(live_terminal.get("agent_profile") or agent_profile),
                    working_directory=working_directory or None,
                )
                terminal_response = _request_cao("GET", f"/terminals/{live_terminal_id}")
                terminal_data = _response_json_or_text(terminal_response)
                return {
                    "ok": True,
                    "restored": False,
                    "leader_id": normalized_leader_id,
                    "session_name": session_name,
                    "terminal_id": live_terminal_id,
                    "leader": terminal_data if isinstance(terminal_data, dict) else live_terminal,
                }

        _request_cao("DELETE", f"/sessions/{session_name}")

    params: Dict[str, str] = {
        "agent_profile": agent_profile,
        "session_name": session_name,
    }
    if provider:
        params["provider"] = provider
    if working_directory:
        params["working_directory"] = working_directory

    created_response = _request_cao("POST", "/sessions", params=params)
    created_leader = _response_json_or_text(created_response)
    if not isinstance(created_leader, dict):
        raise HTTPException(status_code=502, detail="Invalid response while restoring team leader")

    new_terminal_id = str(created_leader.get("id") or "").strip()
    restored_session_name = str(created_leader.get("session_name") or session_name).strip()
    if not new_terminal_id:
        raise HTTPException(status_code=502, detail="Missing leader terminal id after restore")

    if normalized_leader_id != new_terminal_id:
        _rekey_leader_id(normalized_leader_id, new_terminal_id)
        normalized_leader_id = new_terminal_id

    _upsert_team_runtime(
        normalized_leader_id,
        terminal_id=new_terminal_id,
        session_name=restored_session_name,
        provider=str(created_leader.get("provider") or provider),
        agent_profile=str(created_leader.get("agent_profile") or agent_profile),
        working_directory=working_directory or None,
    )

    return {
        "ok": True,
        "restored": True,
        "leader_id": normalized_leader_id,
        "session_name": restored_session_name,
        "terminal_id": new_terminal_id,
        "leader": created_leader,
    }


def _resolve_sender_id(receiver_id: str) -> Optional[str]:
    try:
        receiver_response = _request_cao("GET", f"/terminals/{receiver_id}")
        receiver_terminal = _response_json_or_text(receiver_response)
        if not isinstance(receiver_terminal, dict):
            return None
        session_name = receiver_terminal.get("session_name")
        if not session_name:
            return None

        terminals_response = _request_cao("GET", f"/sessions/{session_name}/terminals")
        terminals = _response_json_or_text(terminals_response)
        if not isinstance(terminals, list):
            return None

        for terminal in terminals:
            terminal_id = terminal.get("id")
            profile = str(terminal.get("agent_profile", "")).lower()
            if terminal_id and terminal_id != receiver_id and "supervisor" in profile:
                return terminal_id

        for terminal in terminals:
            terminal_id = terminal.get("id")
            if terminal_id and terminal_id != receiver_id:
                return terminal_id
    except Exception as exc:
        logger.warning("Failed to resolve sender for receiver %s: %s", receiver_id, exc)

    return None


def _build_organization(terminals: List[Dict[str, Any]]) -> Dict[str, Any]:
    terminals_by_id = {
        terminal["id"]: terminal for terminal in terminals if isinstance(terminal.get("id"), str)
    }
    teams_from_db = _list_teams()
    team_runtimes = {
        leader_id: _get_team_runtime(leader_id)
        for leader_id in teams_from_db
    }

    main_candidates = [terminal for terminal in terminals if terminal.get("is_main")]
    leaders_by_session: Dict[str, List[Dict[str, Any]]] = {}
    for candidate in main_candidates:
        session_name = str(candidate.get("session_name", "") or "")
        leaders_by_session.setdefault(session_name, []).append(candidate)

    leaders: List[Dict[str, Any]] = []
    demoted_main_ids: set[str] = set()
    for session_name, candidates in leaders_by_session.items():
        if len(candidates) == 1:
            leaders.append(candidates[0])
            continue

        chosen_leader = next(
            (
                candidate
                for candidate in candidates
                if str(candidate.get("id", "")) in teams_from_db
            ),
            candidates[0],
        )
        leaders.append(chosen_leader)
        chosen_id = str(chosen_leader.get("id", ""))
        for candidate in candidates:
            candidate_id = str(candidate.get("id", ""))
            if candidate_id and candidate_id != chosen_id:
                demoted_main_ids.add(candidate_id)

    leader_ids = {str(terminal.get("id", "")) for terminal in leaders}
    for leader_id in teams_from_db:
        if leader_id in leader_ids:
            continue
        runtime = team_runtimes.get(leader_id) or {}
        runtime_terminal_id = str((runtime or {}).get("terminal_id") or "").strip()
        team_leader = terminals_by_id.get(runtime_terminal_id) or terminals_by_id.get(leader_id)

        if team_leader:
            team_leader_copy = dict(team_leader)
            team_leader_copy["is_main"] = True
            team_leader_copy["team_type"] = "independent_worker_team"
            leaders.append(team_leader_copy)
            leader_ids.add(str(team_leader_copy.get("id", "")))
            continue

        offline_leader: Dict[str, Any] = {
            "id": leader_id,
            "provider": str((runtime or {}).get("provider") or DEFAULT_PROVIDER),
            "agent_profile": str((runtime or {}).get("agent_profile") or "code_supervisor"),
            "session_name": str((runtime or {}).get("session_name") or ""),
            "status": "OFFLINE",
            "is_main": True,
            "is_offline": True,
            "team_type": "offline_team",
            "last_active": None,
        }
        leaders.append(offline_leader)
        leader_ids.add(leader_id)

    workers = []
    for terminal in terminals:
        terminal_id = str(terminal.get("id", ""))
        if not terminal_id or terminal_id in leader_ids:
            continue
        if terminal_id in demoted_main_ids:
            workers.append(terminal)
            continue
        if not terminal.get("is_main"):
            workers.append(terminal)
    worker_ids = {
        str(worker.get("id", "")) for worker in workers if isinstance(worker.get("id"), str)
    }
    links_from_db = _list_worker_links()
    team_aliases = _list_team_aliases()
    team_workdirs = _list_team_working_directories()
    agent_aliases = _list_agent_aliases()

    for terminal in terminals:
        terminal_id = str(terminal.get("id", ""))
        if terminal_id and terminal_id in agent_aliases:
            terminal["alias"] = agent_aliases[terminal_id]

    for leader in leaders:
        leader_id = str(leader.get("id", ""))
        if leader_id:
            _register_team(leader_id)

    inferred_worker_to_leader: Dict[str, str] = {}
    leaders_by_session: Dict[str, List[str]] = {}
    for leader in leaders:
        session_name = str(leader.get("session_name", ""))
        leader_id = str(leader.get("id", ""))
        if session_name and leader_id:
            leaders_by_session.setdefault(session_name, []).append(leader_id)

    for worker in workers:
        worker_id = str(worker.get("id", ""))
        if not worker_id:
            continue

        if worker_id in links_from_db:
            linked_leader = links_from_db[worker_id]
            if linked_leader in terminals_by_id:
                inferred_worker_to_leader[worker_id] = linked_leader
            continue

        session_name = str(worker.get("session_name", ""))
        session_leaders = leaders_by_session.get(session_name, [])
        if len(session_leaders) == 1:
            leader_id = session_leaders[0]
            inferred_worker_to_leader[worker_id] = leader_id
            _set_worker_link(worker_id, leader_id)

    inbox_inferred = _infer_worker_leader_links_from_inbox(leader_ids, worker_ids)
    for worker_id, leader_id in inbox_inferred.items():
        if worker_id in inferred_worker_to_leader:
            continue
        if leader_id not in terminals_by_id:
            continue
        inferred_worker_to_leader[worker_id] = leader_id
        _set_worker_link(worker_id, leader_id)

    session_name_inferred = _infer_worker_leader_links_from_session_name(
        leaders,
        workers,
        inferred_worker_to_leader,
    )
    for worker_id, leader_id in session_name_inferred.items():
        if worker_id in inferred_worker_to_leader:
            continue
        if leader_id not in terminals_by_id:
            continue
        inferred_worker_to_leader[worker_id] = leader_id
        _set_worker_link(worker_id, leader_id)

    if len(leaders) == 1:
        single_leader_id = str(leaders[0].get("id", ""))
        if single_leader_id:
            for worker in workers:
                worker_id = str(worker.get("id", ""))
                if not worker_id or worker_id in inferred_worker_to_leader:
                    continue
                inferred_worker_to_leader[worker_id] = single_leader_id
                _set_worker_link(worker_id, single_leader_id)

    members_by_leader: Dict[str, List[Dict[str, Any]]] = {}
    for worker in workers:
        worker_id = str(worker.get("id", ""))
        leader_id = inferred_worker_to_leader.get(worker_id)
        if leader_id:
            worker["leader_id"] = leader_id
            members_by_leader.setdefault(leader_id, []).append(worker)

    leader_groups: List[Dict[str, Any]] = []
    for leader in leaders:
        leader_id = str(leader.get("id", ""))
        leader_groups.append(
            {
                "leader": leader,
                "team_alias": team_aliases.get(leader_id),
                "team_working_directory": team_workdirs.get(leader_id),
                "members": sorted(
                    members_by_leader.get(leader_id, []),
                    key=lambda item: str(item.get("last_active", "")),
                    reverse=True,
                ),
            }
        )

    assigned_worker_ids = set(inferred_worker_to_leader.keys())
    unassigned_workers = [
        worker for worker in workers if str(worker.get("id", "")) not in assigned_worker_ids
    ]

    return {
        "leaders": leaders,
        "workers": workers,
        "leader_groups": leader_groups,
        "unassigned_workers": sorted(
            unassigned_workers,
            key=lambda item: str(item.get("last_active", "")),
            reverse=True,
        ),
    }

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CONTROL_PANEL_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if (
        path == "/health"
        or path.startswith("/auth/")
        or path.startswith("/console/internal/")
    ):
        return await call_next(request)

    if not (
        path.startswith("/console/")
        or path.startswith("/api/")
    ):
        return await call_next(request)

    if not _is_authenticated(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    return await call_next(request)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint for the control panel."""
    try:
        # Also check if cao-server is reachable
        response = await asyncio.to_thread(requests.get, f"{CAO_SERVER_URL}/health", timeout=5)
        cao_status = "healthy" if response.status_code == 200 else "unhealthy"
    except Exception:
        cao_status = "unreachable"

    return {
        "status": "healthy",
        "cao_server_status": cao_status,
    }


@app.post("/auth/login")
async def login(payload: LoginRequest) -> JSONResponse:
    if payload.password != CONSOLE_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid password")

    token = _create_session()
    return _build_cookie_response({"ok": True}, token)


@app.post("/auth/logout")
async def logout(request: Request) -> JSONResponse:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        _sessions.pop(token, None)
    return _build_cookie_response({"ok": True}, None)


@app.post("/console/ws-token", response_model=WsTokenResponse)
async def create_console_ws_token() -> WsTokenResponse:
    token = _create_ws_token()
    return WsTokenResponse(token=token, expires_in=WS_TOKEN_TTL_SECONDS)


@app.post("/console/terminals/shell")
async def console_create_shell_terminal(
    payload: Optional[ConsoleCreateShellTerminalRequest] = None,
) -> Dict[str, Any]:
    try:
        terminal = await asyncio.to_thread(
            terminal_service.create_shell_terminal,
            None,
            payload.working_directory if payload else None,
        )
        working_directory = await asyncio.to_thread(terminal_service.get_working_directory, terminal.id)
        return {
            "ok": True,
            "terminal_id": terminal.id,
            "session_name": terminal.session_name,
            "provider": terminal.provider,
            "working_directory": working_directory,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to create shell terminal: {exc}")


@app.get("/auth/me")
async def me(request: Request) -> Dict[str, Any]:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    expires_at = _session_expires_at(token) if token else None
    return {
        "authenticated": expires_at is not None,
        "session_expires_at": int(expires_at) if expires_at else None,
    }


@app.get("/console/provider-config/summary")
async def console_provider_config_summary() -> Dict[str, Any]:
    return await asyncio.to_thread(_build_provider_guide_summary)


@app.get("/console/provider-config/providers/{provider_id}")
async def console_provider_config_provider(provider_id: str) -> Dict[str, Any]:
    return await asyncio.to_thread(_build_single_provider_guide, provider_id)


@app.get("/console/provider-config/{provider_id}/file")
async def console_provider_config_file(provider_id: str) -> Dict[str, Any]:
    return await asyncio.to_thread(_read_provider_config_file, provider_id)


@app.put("/console/provider-config/{provider_id}/file")
async def console_provider_config_file_save(
    provider_id: str, payload: ProviderConfigFileUpdateRequest
) -> Dict[str, Any]:
    return await asyncio.to_thread(_save_provider_config_file, provider_id, payload.content)


@app.post("/console/provider-config/onboarding")
async def console_provider_config_onboarding(payload: ProviderConfigDismissRequest) -> Dict[str, Any]:
    onboarding = await asyncio.to_thread(set_onboarding_state, dismissed=payload.dismissed)
    return {"ok": True, "onboarding": onboarding}


@app.post("/console/provider-config/apply")
async def console_provider_config_apply(payload: ProviderConfigApplyRequest) -> Dict[str, Any]:
    provider_id = payload.provider_id.strip()
    provider_meta = next(
        (item for item in CONTROL_PANEL_PROVIDER_GUIDES if item["id"] == provider_id),
        None,
    )
    if provider_meta is None:
        raise HTTPException(status_code=400, detail=f"Unsupported provider: {provider_id}")

    if payload.mode == "api" and not provider_meta.get("supports_api_config"):
        raise HTTPException(status_code=400, detail=f"{provider_id} does not support API configuration")

    if payload.mode == "account" and not provider_meta.get("supports_account_login"):
        raise HTTPException(status_code=400, detail=f"{provider_id} does not support account login")

    existing_settings = await asyncio.to_thread(_get_provider_saved_settings, provider_id)
    existing_feishu = existing_settings.get("feishu")
    existing_feishu_data = dict(existing_feishu) if isinstance(existing_feishu, dict) else {}

    api_base_url = (payload.api_base_url or "").strip() or str(existing_settings.get("api_base_url") or "").strip()
    api_key = (payload.api_key or "").strip() or str(existing_settings.get("api_key") or "").strip()
    default_model = (payload.default_model or "").strip() or str(existing_settings.get("default_model") or "").strip()

    if payload.mode == "api":
        if not api_base_url:
            raise HTTPException(status_code=400, detail="api_base_url is required in API mode")
        if provider_id in {"claude_code", "openclaw", "codex"} and not api_key:
            raise HTTPException(status_code=400, detail="api_key is required in API mode")
        if not default_model:
            raise HTTPException(status_code=400, detail="default_model is required in API mode")

    saved_path: Optional[str] = None
    command_summary: Optional[str] = None

    try:
        if provider_id == "claude_code" and payload.mode == "api":
            saved_path = str(
                await asyncio.to_thread(_write_claude_settings, api_base_url, api_key, default_model)
            )
        elif provider_id == "codex" and payload.mode == "api":
            saved_path = str(await asyncio.to_thread(_write_codex_config, default_model, api_base_url))
            await asyncio.to_thread(_write_codex_auth, api_key)
        elif provider_id == "openclaw" and payload.mode == "api":
            compatibility = payload.compatibility or "openai"
            if (payload.api_key or "").strip():
                command = [
                    "openclaw",
                    "onboard",
                    "--non-interactive",
                    "--accept-risk",
                    "--skip-ui",
                    "--skip-health",
                    "--skip-skills",
                    "--skip-search",
                    "--no-install-daemon",
                    "--auth-choice",
                    "custom-api-key",
                    "--custom-api-key",
                    api_key,
                    "--custom-base-url",
                    api_base_url,
                    "--custom-model-id",
                    default_model,
                    "--custom-compatibility",
                    compatibility,
                    "--json",
                ]
                result = await asyncio.to_thread(_run_provider_command, command, timeout=60)
                if result.returncode != 0:
                    raise HTTPException(
                        status_code=500,
                        detail=(result.stderr or result.stdout or "OpenClaw onboard failed").strip(),
                    )
                command_summary = " ".join(command[:6]) + " ..."
                saved_path = str(_provider_settings_path("openclaw"))
            else:
                saved_path = str(
                    await asyncio.to_thread(
                        _write_openclaw_api_settings,
                        api_base_url,
                        default_model,
                        compatibility,
                    )
                )
            if payload.feishu and payload.feishu.enabled:
                feishu = payload.feishu
                app_id = (feishu.app_id or "").strip() or str(existing_feishu_data.get("app_id") or "").strip()
                app_secret = (feishu.app_secret or "").strip() or str(existing_feishu_data.get("app_secret") or "").strip()
                verification_token = (feishu.verification_token or "").strip() or str(existing_feishu_data.get("verification_token") or "").strip()
                if not app_id or not app_secret:
                    raise HTTPException(
                        status_code=400,
                        detail="OpenClaw Feishu channel requires app_id and app_secret",
                    )
                if feishu.connection_mode == "webhook" and not verification_token:
                    raise HTTPException(
                        status_code=400,
                        detail="OpenClaw Feishu webhook mode requires verification_token",
                    )
                saved_path = str(
                    await asyncio.to_thread(
                        _merge_openclaw_feishu_config,
                        domain=feishu.domain,
                        connection_mode=feishu.connection_mode,
                        app_id=app_id,
                        app_secret=app_secret,
                        bot_name=(feishu.bot_name or "").strip(),
                        verification_token=verification_token or None,
                        dm_policy=feishu.dm_policy,
                        account_id=(feishu.account_id or "main").strip() or "main",
                    )
                )
        runtime_payload: Dict[str, Any] = {
            "mode": payload.mode,
            "api_base_url": api_base_url or None,
            "api_key": api_key or None,
            "default_model": default_model or None,
            "compatibility": payload.compatibility or existing_settings.get("compatibility") or None,
        }
        if payload.mode == "account":
            runtime_payload["login_completed_at"] = datetime.now(timezone.utc).isoformat()
        if payload.feishu:
            runtime_payload["feishu"] = {
                **existing_feishu_data,
                **payload.feishu.model_dump(exclude_none=True),
                "app_id": (payload.feishu.app_id or "").strip() or existing_feishu_data.get("app_id"),
                "app_secret": (payload.feishu.app_secret or "").strip() or existing_feishu_data.get("app_secret"),
                "verification_token": (payload.feishu.verification_token or "").strip() or existing_feishu_data.get("verification_token"),
            }

        settings = await asyncio.to_thread(update_provider_runtime_settings, provider_id, runtime_payload)
        onboarding = await asyncio.to_thread(set_onboarding_state, completed=True)
        return {
            "ok": True,
            "provider_id": provider_id,
            "saved_path": saved_path,
            "command": command_summary,
            "settings": settings,
            "onboarding": onboarding,
        }
    except HTTPException:
        raise
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail=f"Provider configuration timed out: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to apply provider configuration: {exc}")


@app.post("/console/provider-config/kiro/callback")
async def console_provider_config_kiro_callback(payload: ProviderCallbackRequest) -> Dict[str, Any]:
    callback_url = payload.callback_url.strip()
    parsed = urlparse(callback_url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="callback_url must use http or https")
    if parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise HTTPException(status_code=400, detail="callback_url must target localhost or 127.0.0.1")

    try:
        response = await asyncio.to_thread(requests.get, callback_url, timeout=20)
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to request callback URL: {exc}")

    await asyncio.to_thread(
        update_provider_runtime_settings,
        "kiro_cli",
        {"mode": "account", "login_completed_at": datetime.now(timezone.utc).isoformat()},
    )
    await asyncio.to_thread(set_onboarding_state, completed=True)
    return {
        "ok": response.ok,
        "status_code": response.status_code,
        "body": response.text[:2000],
    }


@app.get("/console/overview")
async def console_overview() -> Dict[str, Any]:
    try:
        terminals = await asyncio.to_thread(_get_terminals_from_sessions)
        provider_counts = Counter(str(t.get("provider", "unknown")) for t in terminals)
        status_counts = Counter(str(t.get("status", "unknown")) for t in terminals)
        profile_counts = Counter(str(t.get("agent_profile", "unknown")) for t in terminals)
        main_agents = [t for t in terminals if t.get("is_main")]
        uptime_seconds = int((datetime.now(timezone.utc) - _service_started_at).total_seconds())
        teams: List[Dict[str, Any]] = []
        team_leaders: List[Dict[str, Any]] = []

        try:
            tasks_overview = await console_tasks()
            if isinstance(tasks_overview, dict):
                teams = list(tasks_overview.get("teams") or [])
                team_leaders = [
                    team["leader"]
                    for team in teams
                    if isinstance(team, dict) and isinstance(team.get("leader"), dict)
                ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to enrich console overview with team data: %s", exc)

        return {
            "uptime_seconds": uptime_seconds,
            "agents_total": len(terminals),
            "main_agents_total": len(main_agents),
            "worker_agents_total": len(terminals) - len(main_agents),
            "provider_counts": dict(provider_counts),
            "status_counts": dict(status_counts),
            "profile_counts": dict(profile_counts),
            "main_agents": main_agents,
            "teams": teams,
            "team_leaders": team_leaders,
        }
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch CAO data: {exc}")


@app.get("/console/agents")
async def console_agents() -> Dict[str, Any]:
    try:
        terminals = await asyncio.to_thread(_get_terminals_from_sessions)
        terminals_sorted = sorted(
            terminals,
            key=lambda item: str(item.get("last_active", "")),
            reverse=True,
        )
        return {"agents": terminals_sorted}
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch agents: {exc}")


@app.get("/console/organization")
async def console_organization() -> Dict[str, Any]:
    try:
        terminals = await asyncio.to_thread(_get_terminals_from_sessions)
        organization = await asyncio.to_thread(_build_organization, terminals)
        return {
            "leaders_total": len(organization["leaders"]),
            "workers_total": len(organization["workers"]),
            **organization,
        }
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch organization: {exc}")


@app.get("/console/workdirs/home")
async def console_home_workdirs() -> Dict[str, Any]:
    home_dir = await asyncio.to_thread(_home_directory)
    directories = await asyncio.to_thread(_list_home_first_level_directories)
    return {
        "home_directory": str(home_dir),
        "directories": directories,
    }


@app.get("/console/assets/teams")
async def console_team_assets() -> Dict[str, Any]:
    terminals = await asyncio.to_thread(_get_terminals_from_sessions)
    organization = await asyncio.to_thread(_build_organization, terminals)
    teams: List[Dict[str, Any]] = []

    for group in organization.get("leader_groups", []):
        if not isinstance(group, dict):
            continue
        leader = group.get("leader")
        if not isinstance(leader, dict):
            continue
        leader_id = str(leader.get("id") or "").strip()
        if not leader_id:
            continue

        working_directory = str(group.get("team_working_directory") or "").strip()
        if not working_directory:
            runtime = await asyncio.to_thread(_get_team_runtime, leader_id)
            working_directory = str((runtime or {}).get("working_directory") or "").strip()

        if not working_directory:
            continue

        team_name = (
            str(group.get("team_alias") or "").strip()
            or str(leader.get("alias") or "").strip()
            or str(leader.get("session_name") or "").strip()
            or leader_id
        )
        teams.append(
            {
                "leader_id": leader_id,
                "team_name": team_name,
                "working_directory": working_directory,
                "leader": leader,
            }
        )

    return {"teams": teams}


@app.get("/console/assets/teams/{leader_id}/tree")
async def console_team_assets_tree(leader_id: str, path: str = "") -> Dict[str, Any]:
    root = await asyncio.to_thread(_resolve_team_working_directory_for_assets, leader_id)
    target = await asyncio.to_thread(_resolve_asset_target, root, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail="Path is not a directory")

    entries: List[Dict[str, Any]] = []
    for child in sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        relative = child.relative_to(root).as_posix()
        stat = child.stat()
        entries.append(
            {
                "name": child.name,
                "path": relative,
                "is_dir": child.is_dir(),
                "size": stat.st_size if child.is_file() else None,
                "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        )

    normalized_path = _resolve_asset_relative_path(path)
    return {
        "leader_id": leader_id,
        "working_directory": str(root),
        "path": normalized_path,
        "entries": entries,
    }


@app.get("/console/assets/teams/{leader_id}/file")
async def console_team_asset_file(leader_id: str, path: str) -> Dict[str, Any]:
    root = await asyncio.to_thread(_resolve_team_working_directory_for_assets, leader_id)
    target = await asyncio.to_thread(_resolve_asset_target, root, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not target.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")

    max_bytes = 1_000_000
    if target.stat().st_size > max_bytes:
        raise HTTPException(status_code=400, detail="File too large to preview online")

    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Only UTF-8 text files can be previewed")

    return {
        "leader_id": leader_id,
        "working_directory": str(root),
        "path": target.relative_to(root).as_posix(),
        "file_path": str(target),
        "content": content,
    }


@app.get("/console/assets/teams/{leader_id}/download")
async def console_team_asset_download(leader_id: str, path: str) -> FileResponse:
    root = await asyncio.to_thread(_resolve_team_working_directory_for_assets, leader_id)
    target = await asyncio.to_thread(_resolve_asset_target, root, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not target.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")

    return FileResponse(path=str(target), filename=target.name)


@app.get("/console/assets/teams/{leader_id}/preview")
async def console_team_asset_preview(leader_id: str, path: str) -> FileResponse:
    root = await asyncio.to_thread(_resolve_team_working_directory_for_assets, leader_id)
    target = await asyncio.to_thread(_resolve_asset_target, root, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not target.is_file():
        raise HTTPException(status_code=400, detail="Path is not a file")

    media_type, _ = mimetypes.guess_type(str(target))
    return FileResponse(
        path=str(target),
        media_type=media_type,
        filename=target.name,
        content_disposition_type="inline",
    )


@app.delete("/console/assets/teams/{leader_id}/entry")
async def console_team_asset_delete(leader_id: str, path: str) -> Dict[str, Any]:
    root = await asyncio.to_thread(_resolve_team_working_directory_for_assets, leader_id)
    target = await asyncio.to_thread(_resolve_asset_target, root, path)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path not found")

    try:
        if target.is_dir():
            import shutil
            await asyncio.to_thread(shutil.rmtree, str(target))
        else:
            await asyncio.to_thread(target.unlink)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"删除失败: {exc.strerror}") from exc

    return {"ok": True, "path": path}


@app.get("/console/tasks")
async def console_tasks() -> Dict[str, Any]:
    try:
        terminals = await asyncio.to_thread(_get_terminals_from_sessions)
        organization = await asyncio.to_thread(_build_organization, terminals)
        terminal_ids = [str(item.get("id", "")) for item in terminals if isinstance(item, dict)]
        latest_task_titles = await asyncio.to_thread(_list_latest_task_titles, terminal_ids)

        try:
            flows_response = await asyncio.to_thread(_request_cao, "GET", "/flows")
            flow_items = await asyncio.to_thread(_response_json_or_text, flows_response)
            if not isinstance(flow_items, list):
                flow_items = []
        except requests.exceptions.RequestException as exc:
            logger.warning("Failed to fetch flows for console tasks: %s", exc)
            flow_items = []

        leader_groups = organization.get("leader_groups", [])
        leader_by_session: Dict[str, str] = {}
        for group in leader_groups:
            if not isinstance(group, dict):
                continue
            leader = group.get("leader")
            if not isinstance(leader, dict):
                continue
            leader_id = str(leader.get("id", "") or "")
            leader_session_name = str(leader.get("session_name", "") or "")
            if leader_id and leader_session_name:
                leader_by_session.setdefault(leader_session_name, leader_id)
        flows_by_leader: Dict[str, List[Dict[str, Any]]] = {}
        unassigned_flows: List[Dict[str, Any]] = []

        for raw_flow in flow_items:
            if not isinstance(raw_flow, dict):
                continue
            flow = _normalize_flow_item(raw_flow)
            flow_session_name = str(flow.get("session_name", "") or "")
            leader_id = leader_by_session.get(flow_session_name)
            if leader_id and flow_session_name:
                flows_by_leader.setdefault(leader_id, []).append(flow)
            else:
                unassigned_flows.append(flow)

        teams: List[Dict[str, Any]] = []
        for group in organization.get("leader_groups", []):
            leader = group.get("leader", {})
            members = group.get("members", [])
            team_agents = [leader, *members]

            instant_tasks: List[Dict[str, Any]] = []
            for agent in team_agents:
                if not isinstance(agent, dict):
                    continue
                if not _is_instant_task_status(str(agent.get("status", ""))):
                    continue
                instant_tasks.append(
                    {
                        "terminal_id": str(agent.get("id", "")),
                        "session_name": agent.get("session_name"),
                        "agent_profile": agent.get("agent_profile"),
                        "task_title": latest_task_titles.get(str(agent.get("id", "")), ""),
                        "status": agent.get("status"),
                        "last_active": agent.get("last_active"),
                    }
                )

            leader_id = str(leader.get("id", ""))
            team_scheduled_tasks = sorted(
                flows_by_leader.get(leader_id, []),
                key=lambda item: str(item.get("next_run") or ""),
            )

            teams.append(
                {
                    "leader": leader,
                    "team_alias": group.get("team_alias"),
                    "members": members,
                    "instant_tasks": instant_tasks,
                    "scheduled_tasks": team_scheduled_tasks,
                }
            )

        return {
            "teams": teams,
            "unassigned_scheduled_tasks": sorted(
                unassigned_flows,
                key=lambda item: str(item.get("next_run") or ""),
            ),
        }
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch tasks: {exc}")


@app.post("/console/tasks/scheduled")
async def console_create_scheduled_task(payload: ConsoleCreateScheduledTaskRequest) -> Dict[str, Any]:
    file_name = payload.file_name.strip() if payload.file_name else ""
    flow_content = payload.flow_content.strip() if payload.flow_content else ""
    flow_display_name = payload.flow_display_name if payload.flow_display_name is not None else None
    leader_id = payload.leader_id.strip() if payload.leader_id else None
    original_flow_path: Optional[Path] = None
    previous_flow_name: Optional[str] = None

    if leader_id:
        if not payload.session_name or not payload.session_name.strip():
            raise HTTPException(status_code=400, detail="session_name is required when leader_id is provided")
        normalized_session_name = _validate_flow_session_name(payload.session_name)
    else:
        normalized_session_name = None

    if file_name:
        original_flow_path = await asyncio.to_thread(_resolve_console_flow_file, file_name)
        flow_path = original_flow_path
        try:
            previous_flow_name = await asyncio.to_thread(_extract_flow_name_from_path, original_flow_path)
        except (HTTPException, OSError):
            previous_flow_name = None
        if flow_content:
            flow_path = await asyncio.to_thread(_overwrite_console_flow_file, flow_path, flow_content)
    elif flow_content:
        flow_path = await asyncio.to_thread(
            _save_flow_content_to_file,
            flow_content,
            normalized_session_name,
        )
    else:
        raise HTTPException(status_code=400, detail="Provide either file_name or flow_content")

    flow_path = await asyncio.to_thread(
        _set_flow_execution_session_name,
        flow_path,
        normalized_session_name,
    )

    body = {"file_path": str(flow_path)}
    target_flow_name = (
        _extract_flow_name_from_content(flow_content)
        if flow_content
        else previous_flow_name or flow_path.stem
    )

    async def _resolve_existing_flow_name_for_path(candidate_path: Path) -> Optional[str]:
        try:
            flows_response = await asyncio.to_thread(_request_cao, "GET", "/flows")
            flow_items = await asyncio.to_thread(_response_json_or_text, flows_response)
            if not isinstance(flow_items, list):
                return None

            flow_path_str = str(candidate_path)
            for item in flow_items:
                if not isinstance(item, dict):
                    continue
                if str(item.get("file_path", "") or "") != flow_path_str:
                    continue
                resolved_name = str(item.get("name", "") or "").strip()
                if resolved_name:
                    return resolved_name
            return None
        except Exception:
            return None

    async def _candidate_flow_names_for_recreate() -> List[str]:
        candidates: List[str] = []

        if previous_flow_name:
            candidates.append(previous_flow_name)

        resolved_existing_name = await _resolve_existing_flow_name_for_path(original_flow_path or flow_path)
        if resolved_existing_name:
            candidates.append(resolved_existing_name)

        extracted_from_payload = _extract_flow_name_from_content(flow_content) if flow_content else None
        if extracted_from_payload:
            candidates.append(extracted_from_payload)

        try:
            flow_file_content = await asyncio.to_thread(flow_path.read_text, encoding="utf-8")
            extracted_from_file = _extract_flow_name_from_content(flow_file_content)
            if extracted_from_file:
                candidates.append(extracted_from_file)
        except Exception:
            pass

        if target_flow_name:
            candidates.append(target_flow_name)

        deduplicated: List[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            normalized = candidate.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduplicated.append(normalized)
        return deduplicated

    async def _create_flow_once() -> Dict[str, Any]:
        response = await asyncio.to_thread(_request_cao, "POST", "/flows", None, body)
        created_flow_response = await asyncio.to_thread(_response_json_or_text, response)
        if not isinstance(created_flow_response, dict):
            raise HTTPException(status_code=500, detail="Invalid flow creation response")
        return created_flow_response

    try:
        created_flow = await _create_flow_once()
    except requests.exceptions.HTTPError as exc:
        if not _is_duplicate_flow_name_error(exc.response):
            raise HTTPException(status_code=502, detail=f"Failed to create scheduled task: {exc}")

        candidate_flow_names = await _candidate_flow_names_for_recreate()
        deleted_flow_name: Optional[str] = None

        for candidate_name in candidate_flow_names:
            logger.info("Flow '%s' already exists, trying recreate via delete '%s'", target_flow_name, candidate_name)
            try:
                await asyncio.to_thread(_request_cao, "DELETE", f"/flows/{candidate_name}")
                deleted_flow_name = candidate_name
                break
            except requests.exceptions.HTTPError as delete_exc:
                status_code = delete_exc.response.status_code if delete_exc.response is not None else None
                if status_code == 404:
                    continue
                raise HTTPException(
                    status_code=502,
                    detail=f"Failed to recreate scheduled task '{candidate_name}': {delete_exc}",
                )
            except requests.exceptions.RequestException as delete_exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Failed to recreate scheduled task '{candidate_name}': {delete_exc}",
                )

        if not deleted_flow_name:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Failed to recreate scheduled task '{target_flow_name}': "
                    f"could not locate matching existing flow to delete"
                ),
            )

        try:
            created_flow = await _create_flow_once()
        except requests.exceptions.RequestException as retry_exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to recreate scheduled task '{deleted_flow_name}': {retry_exc}",
            )
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to create scheduled task: {exc}")

    try:
        flow_name = str(created_flow.get("name", ""))
        if not flow_name:
            raise HTTPException(status_code=500, detail="Flow name missing in response")

        if previous_flow_name and previous_flow_name != flow_name:
            await asyncio.to_thread(_remove_flow_display_name, previous_flow_name)
        await asyncio.to_thread(_upsert_flow_display_name, flow_name, flow_display_name)

        return {
            "ok": True,
            "flow": created_flow,
            "leader_id": leader_id,
            "saved_file_path": str(flow_path),
        }
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to create scheduled task: {exc}")


@app.get("/console/tasks/scheduled/files")
async def console_list_scheduled_task_files() -> Dict[str, Any]:
    files = await asyncio.to_thread(_list_console_flow_files)
    return {"files": files}


@app.get("/console/tasks/scheduled/files/{file_name:path}")
async def console_get_scheduled_task_file(file_name: str) -> Dict[str, Any]:
    flow_path = await asyncio.to_thread(_resolve_console_flow_file, file_name)
    content = await asyncio.to_thread(flow_path.read_text, encoding="utf-8")
    flow_root_dir = await asyncio.to_thread(_console_flow_root_dir)
    relative_name = flow_path.relative_to(flow_root_dir).as_posix()
    try:
        flow_name = await asyncio.to_thread(_extract_flow_name_from_content, content)
    except HTTPException:
        flow_name = flow_path.stem
    return {
        "file_name": relative_name,
        "flow_name": flow_name,
        "display_name": await asyncio.to_thread(_get_flow_display_name, flow_name),
        "file_path": str(flow_path),
        "content": content,
    }


@app.post("/console/tasks/scheduled/{flow_name}/run")
async def console_run_scheduled_task(flow_name: str) -> Dict[str, Any]:
    try:
        await _sync_bound_flow_session_name(flow_name)
        response = await asyncio.to_thread(_request_cao, "POST", f"/flows/{flow_name}/run")
        result = await asyncio.to_thread(_response_json_or_text, response)
        return {"ok": True, "result": result}
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to run scheduled task: {exc}")


@app.post("/console/tasks/scheduled/{flow_name}/enable")
async def console_enable_scheduled_task(flow_name: str) -> Dict[str, Any]:
    try:
        response = await asyncio.to_thread(_request_cao, "POST", f"/flows/{flow_name}/enable")
        result = await asyncio.to_thread(_response_json_or_text, response)
        return {"ok": True, "result": result}
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to enable scheduled task: {exc}")


@app.post("/console/tasks/scheduled/{flow_name}/disable")
async def console_disable_scheduled_task(flow_name: str) -> Dict[str, Any]:
    try:
        response = await asyncio.to_thread(_request_cao, "POST", f"/flows/{flow_name}/disable")
        result = await asyncio.to_thread(_response_json_or_text, response)
        return {"ok": True, "result": result}
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to disable scheduled task: {exc}")


@app.delete("/console/tasks/scheduled/{flow_name}")
async def console_delete_scheduled_task(flow_name: str) -> Dict[str, Any]:
    try:
        response = await asyncio.to_thread(_request_cao, "DELETE", f"/flows/{flow_name}")
        result = await asyncio.to_thread(_response_json_or_text, response)
        await asyncio.to_thread(_remove_flow_display_name, flow_name)
        return {"ok": True, "result": result}
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to delete scheduled task: {exc}")


@app.get("/console/agent-profiles")
async def console_agent_profiles() -> Dict[str, Any]:
    profiles = await asyncio.to_thread(_list_available_agent_profiles)
    profile_options = await asyncio.to_thread(_list_available_agent_profile_options, profiles)
    return {
        "profiles": profiles,
        "profile_options": profile_options,
    }


@app.post("/console/agent-profiles")
async def console_create_agent_profile(payload: AgentProfileCreateRequest) -> Dict[str, Any]:
    if payload.content is not None:
        created_name, created_path = await asyncio.to_thread(
            _create_local_agent_profile_from_content,
            payload.name,
            payload.content,
        )
    else:
        if not payload.description or not payload.system_prompt:
            raise HTTPException(
                status_code=400,
                detail="description and system_prompt are required when content is not provided",
            )
        created_path = await asyncio.to_thread(
            _create_local_agent_profile,
            payload.name,
            payload.description,
            payload.system_prompt,
            payload.provider,
        )
        created_name = payload.name.strip()

    if payload.name.strip() and payload.content is not None and payload.name.strip() != created_name:
        logger.info(
            "Profile name in payload ('%s') differs from frontmatter ('%s'); using frontmatter",
            payload.name,
            created_name,
        )

    await asyncio.to_thread(_upsert_profile_display_name, created_name, payload.display_name)
    return {
        "ok": True,
        "profile": created_name,
        "file_path": str(created_path),
    }


@app.get("/console/agent-profiles/files")
async def console_list_agent_profile_files() -> Dict[str, Any]:
    files = await asyncio.to_thread(_list_local_agent_profile_files)
    return {"files": files}


@app.get("/console/agent-profiles/files/{file_name}")
async def console_get_agent_profile_file(file_name: str) -> Dict[str, Any]:
    profile_name = Path(file_name).stem
    profile_path = _profile_file_path(profile_name)
    exists = await asyncio.to_thread(profile_path.exists)
    if not exists or profile_path.name != file_name:
        raise HTTPException(status_code=404, detail="Agent profile not found")

    content = await asyncio.to_thread(profile_path.read_text, encoding="utf-8")
    display_name = _resolve_profile_display_name(profile_name, profile_path)
    return {
        "profile": profile_name,
        "file_name": profile_path.name,
        "file_path": str(profile_path),
        "content": content,
        "display_name": display_name,
    }


@app.get("/console/agent-profiles/{profile_name}")
async def console_get_agent_profile(profile_name: str) -> Dict[str, Any]:
    profile_path = _profile_file_path(profile_name)
    exists = await asyncio.to_thread(profile_path.exists)
    if not exists:
        raise HTTPException(status_code=404, detail="Agent profile not found")

    content = await asyncio.to_thread(profile_path.read_text, encoding="utf-8")

    return {
        "profile": profile_name,
        "file_path": str(profile_path),
        "content": content,
    }


@app.put("/console/agent-profiles/{profile_name}")
async def console_update_agent_profile(
    profile_name: str,
    payload: AgentProfileUpdateRequest,
) -> Dict[str, Any]:
    AGENT_CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    profile_path = _profile_file_path(profile_name)
    exists = await asyncio.to_thread(profile_path.exists)
    if not exists:
        raise HTTPException(status_code=404, detail="Agent profile not found")

    metadata = await asyncio.to_thread(_validate_profile_markdown_content, payload.content)
    content_profile_name = _validate_profile_name(str(metadata.get("name", "")))
    target_profile_path = _profile_file_path(content_profile_name)

    if target_profile_path.exists() and target_profile_path != profile_path:
        raise HTTPException(status_code=409, detail="Agent profile name already exists")

    if target_profile_path != profile_path:
        await asyncio.to_thread(profile_path.rename, target_profile_path)
        await asyncio.to_thread(_remove_profile_display_name, profile_name)
        profile_name = content_profile_name
        profile_path = target_profile_path

    await asyncio.to_thread(profile_path.write_text, payload.content, encoding="utf-8")
    await asyncio.to_thread(_upsert_profile_display_name, profile_name, payload.display_name)
    return {"ok": True, "profile": profile_name, "file_path": str(profile_path)}


@app.post("/console/agent-profiles/{profile_name}/install")
async def console_install_agent_profile(profile_name: str) -> Dict[str, Any]:
    profile_path = _profile_file_path(profile_name)
    exists = await asyncio.to_thread(profile_path.exists)
    if not exists:
        raise HTTPException(status_code=404, detail="Agent profile not found")

    try:
        process = await asyncio.to_thread(
            subprocess.run,
            ["uv", "run", "cao", "install", str(profile_path)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to execute install command: {exc}")

    return {
        "ok": process.returncode == 0,
        "profile": profile_name,
        "command": f"uv run cao install {profile_path}",
        "return_code": process.returncode,
        "stdout": process.stdout,
        "stderr": process.stderr,
    }


@app.delete("/console/agent-profiles/{profile_name}")
async def console_delete_agent_profile(profile_name: str) -> Dict[str, Any]:
    normalized_profile = _validate_profile_name(profile_name)
    profile_path = _profile_file_path(normalized_profile)
    exists = await asyncio.to_thread(profile_path.exists)
    if not exists:
        raise HTTPException(status_code=404, detail="Agent profile not found")

    try:
        uninstall_process = await asyncio.to_thread(
            subprocess.run,
            ["uv", "run", "cao", "uninstall", normalized_profile],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to execute uninstall command: {exc}")

    # Even if uninstall fails, we still remove local profile file to satisfy
    # explicit delete request from organization management UI.
    # The uninstall command may already remove this file, so deletion here must
    # be idempotent and should not fail when file is already gone.
    await asyncio.to_thread(lambda: profile_path.unlink(missing_ok=True))
    await asyncio.to_thread(_remove_profile_display_name, normalized_profile)

    return {
        "ok": uninstall_process.returncode == 0,
        "profile": normalized_profile,
        "command": f"uv run cao uninstall {normalized_profile}",
        "return_code": uninstall_process.returncode,
        "stdout": uninstall_process.stdout,
        "stderr": uninstall_process.stderr,
        "file_deleted": True,
    }


@app.post("/console/organization/link")
async def console_link_worker(payload: OrgLinkRequest) -> Dict[str, Any]:
    worker_id = payload.worker_id.strip()
    leader_id = payload.leader_id.strip() if payload.leader_id else None

    try:
        worker_response = await asyncio.to_thread(_request_cao, "GET", f"/terminals/{worker_id}")
        worker_terminal = await asyncio.to_thread(_response_json_or_text, worker_response)
        if not isinstance(worker_terminal, dict):
            raise HTTPException(status_code=400, detail="Invalid worker terminal")
        worker_profile = str(worker_terminal.get("agent_profile", "")).lower()
        if "supervisor" in worker_profile:
            raise HTTPException(status_code=400, detail="worker_id cannot be a main agent")

        if leader_id:
            leader_response = await asyncio.to_thread(_request_cao, "GET", f"/terminals/{leader_id}")
            leader_terminal = await asyncio.to_thread(_response_json_or_text, leader_response)
            if not isinstance(leader_terminal, dict):
                raise HTTPException(status_code=400, detail="Invalid leader terminal")
            leader_profile = str(leader_terminal.get("agent_profile", "")).lower()
            if "supervisor" not in leader_profile:
                raise HTTPException(status_code=400, detail="leader_id must be a main agent")
            await asyncio.to_thread(_register_team, leader_id)
            await asyncio.to_thread(_set_worker_link, worker_id, leader_id)
        else:
            await asyncio.to_thread(_remove_worker_link, worker_id)

        return {"ok": True, "worker_id": worker_id, "leader_id": leader_id}
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to link organization: {exc}")


@app.post("/console/internal/organization/link")
async def console_internal_link_worker(payload: OrgLinkRequest) -> Dict[str, Any]:
    """Internal API to link a worker to a leader without control-panel auth."""
    return await console_link_worker(payload)


@app.post("/console/internal/agent-alias/auto-set")
async def console_auto_set_agent_alias(payload: Dict[str, str]) -> Dict[str, Any]:
    """Internal API to automatically set agent alias based on profile display name."""
    terminal_id = payload.get("terminal_id", "").strip()
    agent_profile = payload.get("agent_profile", "").strip()

    if not terminal_id or not agent_profile:
        raise HTTPException(status_code=400, detail="terminal_id and agent_profile are required")

    display_name = await asyncio.to_thread(_resolve_available_profile_display_name, agent_profile)
    if display_name:
        await asyncio.to_thread(_set_agent_alias, terminal_id, display_name)
        return {"ok": True, "terminal_id": terminal_id, "agent_alias": display_name}

    return {"ok": True, "terminal_id": terminal_id, "agent_alias": None}


@app.post("/console/organization/create")
async def console_create_org_agent(payload: OrgCreateRequest) -> Dict[str, Any]:
    params: Dict[str, str] = {"agent_profile": payload.agent_profile}
    if payload.provider:
        params["provider"] = payload.provider

    explicit_working_directory = (payload.working_directory or "").strip()
    if payload.team_workdir_mode and payload.role_type != "main":
        raise HTTPException(status_code=400, detail="team_workdir_mode is only supported for main role")

    if payload.team_workdir_name and payload.role_type != "main":
        raise HTTPException(status_code=400, detail="team_workdir_name is only supported for main role")

    main_team_working_directory: Optional[str] = None
    if payload.role_type == "main":
        mode = payload.team_workdir_mode
        dir_name = payload.team_workdir_name

        if mode and not dir_name:
            raise HTTPException(status_code=400, detail="team_workdir_name is required when team_workdir_mode is set")
        if dir_name and not mode:
            raise HTTPException(status_code=400, detail="team_workdir_mode is required when team_workdir_name is set")

        if mode == "existing":
            main_team_working_directory = await asyncio.to_thread(
                _resolve_home_level1_directory,
                dir_name or "",
                must_exist=True,
                create_if_missing=False,
            )
        elif mode == "new":
            main_team_working_directory = await asyncio.to_thread(
                _resolve_home_level1_directory,
                dir_name or "",
                must_exist=True,
                create_if_missing=True,
            )
        elif explicit_working_directory:
            main_team_working_directory = explicit_working_directory

        if main_team_working_directory:
            params["working_directory"] = main_team_working_directory
    elif explicit_working_directory:
        params["working_directory"] = explicit_working_directory

    # 如果没有传入agent_alias，使用岗位配置中的展示名称作为默认值
    agent_alias_to_use = payload.agent_alias
    if not agent_alias_to_use:
        display_name = await asyncio.to_thread(
            _resolve_available_profile_display_name,
            payload.agent_profile,
        )
        if display_name:
            agent_alias_to_use = display_name

    try:
        if payload.role_type == "main":
            created_response = await asyncio.to_thread(_request_cao, "POST", "/sessions", params)
            created_agent = await asyncio.to_thread(_response_json_or_text, created_response)
            if isinstance(created_agent, dict) and isinstance(created_agent.get("id"), str):
                leader_id = created_agent["id"]
                await asyncio.to_thread(_register_team, leader_id)
                if main_team_working_directory:
                    await asyncio.to_thread(
                        _set_team_working_directory,
                        leader_id,
                        main_team_working_directory,
                    )
                if payload.team_alias:
                    await asyncio.to_thread(_set_team_alias, leader_id, payload.team_alias)
                if agent_alias_to_use:
                    await asyncio.to_thread(_set_agent_alias, leader_id, agent_alias_to_use)
                await asyncio.to_thread(
                    _upsert_team_runtime,
                    leader_id,
                    terminal_id=leader_id,
                    session_name=str(created_agent.get("session_name") or "").strip() or None,
                    provider=str(created_agent.get("provider") or params.get("provider") or "").strip() or None,
                    agent_profile=str(created_agent.get("agent_profile") or payload.agent_profile).strip() or None,
                    working_directory=str(
                        main_team_working_directory
                        or params.get("working_directory")
                        or ""
                    ).strip()
                    or None,
                )
            return {
                "ok": True,
                "role_type": payload.role_type,
                "leader_id": None,
                "agent": created_agent,
            }

        if payload.leader_id:
            leader_response = await asyncio.to_thread(
                _request_cao, "GET", f"/terminals/{payload.leader_id}"
            )
            leader_terminal = await asyncio.to_thread(_response_json_or_text, leader_response)
            if not isinstance(leader_terminal, dict):
                raise HTTPException(status_code=400, detail="Invalid leader_id")
            session_name = leader_terminal.get("session_name")
            if not session_name:
                raise HTTPException(status_code=400, detail="leader has no session")

            team_workdirs = await asyncio.to_thread(_list_team_working_directories)
            inherited_working_directory = team_workdirs.get(payload.leader_id)
            if not inherited_working_directory:
                inherited_working_directory = str(leader_terminal.get("working_directory", "") or "").strip()
            if inherited_working_directory:
                params["working_directory"] = inherited_working_directory

            created_response = await asyncio.to_thread(
                _request_cao,
                "POST",
                f"/sessions/{session_name}/terminals",
                params,
            )
            created_agent = await asyncio.to_thread(_response_json_or_text, created_response)
            if isinstance(created_agent, dict) and isinstance(created_agent.get("id"), str):
                await asyncio.to_thread(_register_team, payload.leader_id)
                worker_id = created_agent["id"]
                await asyncio.to_thread(_set_worker_link, worker_id, payload.leader_id)
                if agent_alias_to_use:
                    await asyncio.to_thread(_set_agent_alias, worker_id, agent_alias_to_use)
            return {
                "ok": True,
                "role_type": payload.role_type,
                "leader_id": payload.leader_id,
                "agent": created_agent,
            }

        created_response = await asyncio.to_thread(_request_cao, "POST", "/sessions", params)
        created_agent = await asyncio.to_thread(_response_json_or_text, created_response)
        created_agent_id = created_agent.get("id") if isinstance(created_agent, dict) else None
        if isinstance(created_agent_id, str):
            await asyncio.to_thread(_register_team, created_agent_id)
            if payload.team_alias:
                await asyncio.to_thread(_set_team_alias, created_agent_id, payload.team_alias)
            if agent_alias_to_use:
                await asyncio.to_thread(_set_agent_alias, created_agent_id, agent_alias_to_use)
            await asyncio.to_thread(
                _upsert_team_runtime,
                created_agent_id,
                terminal_id=created_agent_id,
                session_name=str(created_agent.get("session_name") or "").strip() or None,
                provider=str(created_agent.get("provider") or params.get("provider") or "").strip() or None,
                agent_profile=str(created_agent.get("agent_profile") or payload.agent_profile).strip() or None,
                working_directory=str(params.get("working_directory") or "").strip() or None,
            )
        return {
            "ok": True,
            "role_type": payload.role_type,
            "leader_id": created_agent_id if isinstance(created_agent_id, str) else None,
            "agent": created_agent,
        }

    except requests.exceptions.HTTPError as exc:
        upstream = exc.response
        if upstream is not None:
            try:
                upstream_body = upstream.json()
            except ValueError:
                upstream_body = upstream.text

            if isinstance(upstream_body, dict):
                detail = upstream_body.get("detail") or upstream_body
            else:
                detail = upstream_body or str(exc)

            raise HTTPException(status_code=upstream.status_code, detail=detail)

        raise HTTPException(status_code=502, detail=f"Failed to create organization agent: {exc}")
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to create organization agent: {exc}")


@app.post("/console/organization/{leader_id}/disband")
async def console_disband_team(leader_id: str, payload: Optional[OrgDisbandRequest] = None) -> Dict[str, Any]:
    normalized_leader_id = leader_id.strip()
    if not normalized_leader_id:
        raise HTTPException(status_code=400, detail="leader_id cannot be empty")

    candidate_leader_id = _resolve_terminal_id_alias(normalized_leader_id)
    team_ids = _list_teams()
    if candidate_leader_id in team_ids:
        normalized_leader_id = candidate_leader_id
    elif normalized_leader_id not in team_ids:
        raise HTTPException(status_code=404, detail="Team not found")

    requested_session_raw = (payload.session_name if payload else None) or ""
    requested_session_raw = requested_session_raw.strip()
    requested_session_name = _validate_flow_session_name(requested_session_raw) if requested_session_raw else None

    leader_session_name: Optional[str] = None

    try:
        leader_response = await asyncio.to_thread(
            _request_cao,
            "GET",
            f"/terminals/{normalized_leader_id}",
        )
        leader_terminal_data = await asyncio.to_thread(_response_json_or_text, leader_response)
        if isinstance(leader_terminal_data, dict):
            leader_session_raw = str(leader_terminal_data.get("session_name", "") or "").strip()
            if leader_session_raw:
                leader_session_name = _validate_flow_session_name(leader_session_raw)
    except requests.exceptions.RequestException as exc:
        logger.warning(
            "Failed to fetch leader terminal %s while disbanding team, fallback to runtime: %s",
            normalized_leader_id,
            exc,
        )

    if not leader_session_name:
        runtime = await asyncio.to_thread(_get_team_runtime, normalized_leader_id)
        runtime_session = str((runtime or {}).get("session_name") or "").strip()
        if runtime_session:
            leader_session_name = _validate_flow_session_name(runtime_session)

    if requested_session_name and leader_session_name and requested_session_name != leader_session_name:
        raise HTTPException(
            status_code=400,
            detail="leader_id and session_name mismatch",
        )

    session_name = requested_session_name or leader_session_name
    result: Dict[str, Any] = {"success": True, "session_deleted": False}
    if session_name:
        try:
            live_sessions = await asyncio.to_thread(_list_live_sessions)
            if session_name in live_sessions:
                delete_response = await asyncio.to_thread(_request_cao, "DELETE", f"/sessions/{session_name}")
                delete_result = await asyncio.to_thread(_response_json_or_text, delete_response)
                result = {
                    "success": True,
                    "session_deleted": True,
                    "delete_result": delete_result,
                }
        except requests.exceptions.RequestException as exc:
            raise HTTPException(status_code=502, detail=f"Failed to disband team session: {exc}")

    await asyncio.to_thread(_remove_team, normalized_leader_id)
    return {
        "ok": True,
        "leader_id": normalized_leader_id,
        "session_name": session_name,
        "result": result,
    }


async def _restart_team_leader_task(
    normalized_leader_id: str,
    payload: OrgLeaderUpdateRequest,
    requested_working_directory: Optional[str],
) -> Dict[str, Any]:
    runtime = await asyncio.to_thread(_get_team_runtime, normalized_leader_id)

    current_leader_terminal: Optional[Dict[str, Any]] = None
    old_terminal_id: Optional[str] = None
    old_session_name: Optional[str] = None
    old_provider: Optional[str] = None

    try:
        current_leader_response = await asyncio.to_thread(
            _request_cao,
            "GET",
            f"/terminals/{normalized_leader_id}",
        )
        current_leader_terminal_data = await asyncio.to_thread(
            _response_json_or_text,
            current_leader_response,
        )
        if isinstance(current_leader_terminal_data, dict):
            current_leader_terminal = current_leader_terminal_data
            old_terminal_id = str(current_leader_terminal.get("id") or "").strip() or None
            old_session_name = (
                str(current_leader_terminal.get("session_name") or "").strip() or None
            )
            old_provider = str(current_leader_terminal.get("provider") or "").strip() or None
    except requests.exceptions.RequestException:
        current_leader_terminal = None

    if not old_terminal_id:
        old_terminal_id = str((runtime or {}).get("terminal_id") or "").strip() or None
    if not old_session_name:
        old_session_name = str((runtime or {}).get("session_name") or "").strip() or None

    if not old_session_name:
        raise HTTPException(status_code=400, detail="leader has no session")

    new_provider = (
        (payload.provider or "").strip()
        or old_provider
        or str((runtime or {}).get("provider") or "").strip()
        or DEFAULT_PROVIDER
    )
    new_profile = payload.agent_profile.strip()
    existing_working_directory = str((runtime or {}).get("working_directory") or "").strip() or None
    if not existing_working_directory:
        team_workdirs = await asyncio.to_thread(_list_team_working_directories)
        existing_working_directory = str(team_workdirs.get(normalized_leader_id) or "").strip() or None
    if not existing_working_directory and current_leader_terminal:
        existing_working_directory = (
            str(current_leader_terminal.get("working_directory") or "").strip() or None
        )
    new_working_directory = requested_working_directory or existing_working_directory

    if old_terminal_id:
        try:
            await asyncio.to_thread(_request_cao, "DELETE", f"/terminals/{old_terminal_id}")
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code != 404:
                raise HTTPException(
                    status_code=502, detail=f"Failed to remove old leader terminal: {exc}"
                )
        except requests.exceptions.RequestException as exc:
            raise HTTPException(status_code=502, detail=f"Failed to remove old leader terminal: {exc}")

    params: Dict[str, str] = {
        "agent_profile": new_profile,
    }
    if new_provider:
        params["provider"] = new_provider
    if new_working_directory:
        params["working_directory"] = new_working_directory

    live_sessions = await asyncio.to_thread(_list_live_sessions)
    try:
        if old_session_name in live_sessions:
            created_response = await asyncio.to_thread(
                _request_cao,
                "POST",
                f"/sessions/{old_session_name}/terminals",
                params,
            )
        else:
            create_session_params = dict(params)
            create_session_params["session_name"] = old_session_name
            created_response = await asyncio.to_thread(
                _request_cao,
                "POST",
                "/sessions",
                create_session_params,
            )
        created_leader = await asyncio.to_thread(_response_json_or_text, created_response)
    except requests.exceptions.HTTPError as exc:
        upstream = exc.response
        if upstream is not None:
            try:
                upstream_body = upstream.json()
            except ValueError:
                upstream_body = upstream.text
            detail = upstream_body.get("detail") if isinstance(upstream_body, dict) else upstream_body
            raise HTTPException(status_code=upstream.status_code, detail=detail or str(exc))
        raise HTTPException(status_code=502, detail=f"Failed to restart team leader: {exc}")
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to restart team leader: {exc}")

    if not isinstance(created_leader, dict):
        raise HTTPException(status_code=502, detail="Invalid response while restarting team leader")

    new_terminal_id = str(created_leader.get("id") or "").strip()
    if not new_terminal_id:
        raise HTTPException(status_code=502, detail="Missing leader terminal id after restart")

    canonical_leader_id = normalized_leader_id
    if normalized_leader_id != new_terminal_id:
        await asyncio.to_thread(_rekey_leader_id, normalized_leader_id, new_terminal_id)
        canonical_leader_id = new_terminal_id

    if payload.team_alias is not None:
        alias_value = payload.team_alias.strip()
        if alias_value:
            await asyncio.to_thread(_set_team_alias, canonical_leader_id, alias_value)

    if new_working_directory:
        await asyncio.to_thread(_set_team_working_directory, canonical_leader_id, new_working_directory)

    await asyncio.to_thread(
        _upsert_team_runtime,
        canonical_leader_id,
        terminal_id=new_terminal_id,
        session_name=str(created_leader.get("session_name") or old_session_name or "").strip() or None,
        provider=str(created_leader.get("provider") or new_provider or "").strip() or None,
        agent_profile=str(created_leader.get("agent_profile") or new_profile).strip() or None,
        working_directory=new_working_directory,
    )

    return {
        "ok": True,
        "leader_id": canonical_leader_id,
        "previous_leader_id": normalized_leader_id,
        "session_name": str(created_leader.get("session_name") or old_session_name or "").strip() or None,
        "leader": created_leader,
    }


@app.put("/console/organization/{leader_id}/leader", status_code=status.HTTP_202_ACCEPTED)
async def console_update_team_leader(
    leader_id: str,
    payload: OrgLeaderUpdateRequest,
) -> Dict[str, Any]:
    normalized_leader_id = leader_id.strip()
    if not normalized_leader_id:
        raise HTTPException(status_code=400, detail="leader_id cannot be empty")

    candidate_leader_id = _resolve_terminal_id_alias(normalized_leader_id)
    team_ids = _list_teams()
    if candidate_leader_id in team_ids:
        normalized_leader_id = candidate_leader_id
    elif normalized_leader_id not in team_ids:
        raise HTTPException(status_code=404, detail="Team not found")

    mode = payload.team_workdir_mode
    dir_name = payload.team_workdir_name
    explicit_working_directory = (payload.working_directory or "").strip()
    if mode and not dir_name:
        raise HTTPException(status_code=400, detail="team_workdir_name is required when team_workdir_mode is set")
    if dir_name and not mode:
        raise HTTPException(status_code=400, detail="team_workdir_mode is required when team_workdir_name is set")

    requested_working_directory: Optional[str] = None
    if mode == "existing":
        requested_working_directory = await asyncio.to_thread(
            _resolve_home_level1_directory,
            dir_name or "",
            must_exist=True,
            create_if_missing=False,
        )
    elif mode == "new":
        requested_working_directory = await asyncio.to_thread(
            _resolve_home_level1_directory,
            dir_name or "",
            must_exist=True,
            create_if_missing=True,
        )
    elif explicit_working_directory:
        requested_working_directory = explicit_working_directory

    async def _restart_task() -> None:
        try:
            await _restart_team_leader_task(
                normalized_leader_id=normalized_leader_id,
                payload=payload,
                requested_working_directory=requested_working_directory,
            )
        except HTTPException as exc:
            logger.warning(
                "Team leader update failed for %s: %s",
                normalized_leader_id,
                getattr(exc, "detail", str(exc)),
            )
        except Exception:
            logger.exception("Failed to restart team leader %s asynchronously", normalized_leader_id)

    asyncio.create_task(_restart_task())

    return {
        "ok": True,
        "queued": True,
        "leader_id": normalized_leader_id,
        "message": "负责人更新任务已提交，后台重启会话中",
    }


@app.post("/console/organization/{leader_id}/clock-out")
async def console_clock_out_team(leader_id: str) -> Dict[str, Any]:
    normalized_leader_id = leader_id.strip()
    if not normalized_leader_id:
        raise HTTPException(status_code=400, detail="leader_id cannot be empty")

    candidate_leader_id = _resolve_terminal_id_alias(normalized_leader_id)
    team_ids = _list_teams()
    if candidate_leader_id in team_ids:
        normalized_leader_id = candidate_leader_id
    elif normalized_leader_id not in team_ids:
        raise HTTPException(status_code=404, detail="Team not found")

    terminals = await asyncio.to_thread(_get_terminals_from_sessions)
    organization = await asyncio.to_thread(_build_organization, terminals)

    target_group: Optional[Dict[str, Any]] = None
    for group in organization.get("leader_groups", []):
        if not isinstance(group, dict):
            continue
        leader = group.get("leader")
        if not isinstance(leader, dict):
            continue
        group_leader_id = str(leader.get("id") or "").strip()
        if group_leader_id == normalized_leader_id:
            target_group = group
            break

    if target_group is None:
        runtime = await asyncio.to_thread(_get_team_runtime, normalized_leader_id)
        runtime_session_name = str((runtime or {}).get("session_name") or "").strip() or None
        await asyncio.to_thread(
            _upsert_team_runtime,
            normalized_leader_id,
            terminal_id=None,
            session_name=runtime_session_name,
            provider=str((runtime or {}).get("provider") or "").strip() or None,
            agent_profile=str((runtime or {}).get("agent_profile") or "").strip() or None,
            working_directory=str((runtime or {}).get("working_directory") or "").strip() or None,
        )
        return {
            "ok": True,
            "leader_id": normalized_leader_id,
            "session_name": runtime_session_name,
            "workers_removed": 0,
            "leader_terminal_exited": False,
            "result": {
                "workers_removed": [],
                "workers_not_found": [],
                "leader_terminal_id": None,
                "leader_terminal_not_found": True,
            },
        }

    leader = target_group.get("leader") if isinstance(target_group.get("leader"), dict) else {}
    members = target_group.get("members") if isinstance(target_group.get("members"), list) else []

    worker_ids: List[str] = []
    for member in members:
        if not isinstance(member, dict):
            continue
        worker_id = str(member.get("id") or "").strip()
        if worker_id:
            worker_ids.append(worker_id)

    removed_worker_ids: List[str] = []
    missing_worker_ids: List[str] = []

    for worker_id in worker_ids:
        try:
            await asyncio.to_thread(_request_cao, "DELETE", f"/terminals/{worker_id}")
            removed_worker_ids.append(worker_id)
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code == 404:
                missing_worker_ids.append(worker_id)
            else:
                raise HTTPException(
                    status_code=502,
                    detail=f"Failed to clock out worker terminal {worker_id}: {exc}",
                )
        except requests.exceptions.RequestException as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to clock out worker terminal {worker_id}: {exc}",
            )
        finally:
            await asyncio.to_thread(_remove_worker_link, worker_id)

    leader_terminal_id = str(leader.get("id") or "").strip() or None
    leader_is_offline = bool(leader.get("is_offline"))
    leader_terminal_exited = False
    leader_terminal_not_found = False

    if leader_terminal_id and not leader_is_offline:
        try:
            await asyncio.to_thread(_request_cao, "DELETE", f"/terminals/{leader_terminal_id}")
            leader_terminal_exited = True
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code == 404:
                leader_terminal_not_found = True
            else:
                raise HTTPException(
                    status_code=502,
                    detail=f"Failed to clock out leader terminal {leader_terminal_id}: {exc}",
                )
        except requests.exceptions.RequestException as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to clock out leader terminal {leader_terminal_id}: {exc}",
            )

    runtime = await asyncio.to_thread(_get_team_runtime, normalized_leader_id)
    session_name = str(leader.get("session_name") or "").strip() or str((runtime or {}).get("session_name") or "").strip() or None
    provider = str(leader.get("provider") or "").strip() or str((runtime or {}).get("provider") or "").strip() or None
    agent_profile = str(leader.get("agent_profile") or "").strip() or str((runtime or {}).get("agent_profile") or "").strip() or None
    working_directory = str((runtime or {}).get("working_directory") or "").strip() or None

    await asyncio.to_thread(
        _upsert_team_runtime,
        normalized_leader_id,
        terminal_id=None,
        session_name=session_name,
        provider=provider,
        agent_profile=agent_profile,
        working_directory=working_directory,
    )

    return {
        "ok": True,
        "leader_id": normalized_leader_id,
        "session_name": session_name,
        "workers_removed": len(removed_worker_ids),
        "leader_terminal_exited": leader_terminal_exited,
        "result": {
            "workers_removed": removed_worker_ids,
            "workers_not_found": missing_worker_ids,
            "leader_terminal_id": leader_terminal_id,
            "leader_terminal_not_found": leader_terminal_not_found,
        },
    }


@app.post("/console/organization/{leader_id}/ensure-online")
async def console_ensure_team_online(leader_id: str) -> Dict[str, Any]:
    try:
        return await asyncio.to_thread(_ensure_team_leader_online, leader_id)
    except requests.exceptions.HTTPError as exc:
        upstream = exc.response
        if upstream is not None:
            try:
                body = upstream.json()
            except ValueError:
                body = upstream.text
            detail = body.get("detail") if isinstance(body, dict) else body
            raise HTTPException(status_code=upstream.status_code, detail=detail or str(exc))
        raise HTTPException(status_code=502, detail=f"Failed to ensure team online: {exc}")
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to ensure team online: {exc}")


@app.post("/console/agents/{terminal_id}/input")
async def send_input_to_agent(terminal_id: str, payload: AgentMessageRequest) -> Dict[str, Any]:
    resolved_terminal_id = _resolve_terminal_id_alias(terminal_id)
    try:
        response = await asyncio.to_thread(
            _request_cao,
            "POST",
            f"/terminals/{resolved_terminal_id}/input",
            {"message": payload.message},
        )
        body = await asyncio.to_thread(_response_json_or_text, response)
        return {"ok": True, "terminal_id": resolved_terminal_id, "result": body}
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to send input: {exc}")


@app.post("/console/agents/{terminal_id}/tmux/input")
async def send_input_to_agent_tmux(terminal_id: str, payload: AgentTmuxInputRequest) -> Dict[str, Any]:
    resolved_terminal_id = _resolve_terminal_id_alias(terminal_id)
    try:
        tmux_session, tmux_window = await asyncio.to_thread(_get_terminal_tmux_target, resolved_terminal_id)
        await asyncio.to_thread(tmux_client.send_raw_input, tmux_session, tmux_window, payload.message)
        if payload.press_enter:
            await asyncio.to_thread(tmux_client.send_special_key, tmux_session, tmux_window, "C-m")
        return {
            "ok": True,
            "terminal_id": resolved_terminal_id,
            "tmux_session": tmux_session,
            "tmux_window": tmux_window,
            "press_enter": payload.press_enter,
        }
    except HTTPException:
        raise
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to locate terminal: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to send tmux input: {exc}")


@app.get("/console/agents/{terminal_id}/tmux/output")
async def get_agent_tmux_output(terminal_id: str, lines: int = 300) -> Dict[str, Any]:
    safe_lines = max(20, min(lines, 1000))
    resolved_terminal_id = _resolve_terminal_id_alias(terminal_id)
    try:
        tmux_session, tmux_window = await asyncio.to_thread(_get_terminal_tmux_target, resolved_terminal_id)
        output = await asyncio.to_thread(
            tmux_client.get_history,
            tmux_session,
            tmux_window,
            safe_lines,
        )
        return {
            "terminal_id": resolved_terminal_id,
            "tmux_session": tmux_session,
            "tmux_window": tmux_window,
            "lines": safe_lines,
            "output": output,
        }
    except HTTPException:
        raise
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to locate terminal: {exc}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read tmux output: {exc}")


@app.websocket("/console/agents/{terminal_id}/tmux/ws")
async def stream_agent_tmux_ws(websocket: WebSocket, terminal_id: str) -> None:
    token = websocket.query_params.get("token")
    if not token or not _consume_ws_token(token):
        await websocket.close(code=4401)
        return

    try:
        resolved_terminal_id = _resolve_terminal_id_alias(terminal_id)
        tmux_session, tmux_window = await asyncio.to_thread(_get_terminal_tmux_target, resolved_terminal_id)
    except Exception:
        await websocket.close(code=4404)
        return

    await websocket.accept()

    last_output = ""

    async def push_output_loop() -> None:
        nonlocal last_output
        while True:
            output = await asyncio.to_thread(
                tmux_client.get_history,
                tmux_session,
                tmux_window,
                500,
            )
            if output != last_output:
                if output.startswith(last_output):
                    delta = output[len(last_output) :]
                    if delta:
                        await websocket.send_text(delta)
                else:
                    await websocket.send_text("\u001bc" + output)
                last_output = output
            await asyncio.sleep(0.2)

    sender_task = asyncio.create_task(push_output_loop())

    try:
        while True:
            message = await websocket.receive_text()
            input_text = ""
            send_enter = False
            resize_cols: Optional[int] = None
            resize_rows: Optional[int] = None

            try:
                payload = json.loads(message)
                if isinstance(payload, dict):
                    raw_input = payload.get("input")
                    if isinstance(raw_input, str):
                        input_text = raw_input
                    send_enter = bool(payload.get("enter"))
                    raw_cols = payload.get("cols")
                    raw_rows = payload.get("rows")
                    if isinstance(raw_cols, int) and isinstance(raw_rows, int):
                        resize_cols = raw_cols
                        resize_rows = raw_rows
                else:
                    input_text = message
            except json.JSONDecodeError:
                input_text = message

            if resize_cols is not None and resize_rows is not None:
                await asyncio.to_thread(
                    tmux_client.resize_window,
                    tmux_session,
                    tmux_window,
                    resize_cols,
                    resize_rows,
                )

            if input_text:
                await asyncio.to_thread(
                    tmux_client.send_raw_input,
                    tmux_session,
                    tmux_window,
                    input_text,
                )

            if send_enter:
                await asyncio.to_thread(
                    tmux_client.send_special_key,
                    tmux_session,
                    tmux_window,
                    "C-m",
                )
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("tmux ws stream failed for %s: %s", terminal_id, exc)
    finally:
        sender_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await sender_task


@app.get("/console/agents/{terminal_id}/stream")
async def stream_agent_output(
    terminal_id: str,
    request: Request,
    max_events: Optional[int] = None,
) -> StreamingResponse:
    async def event_generator():
        last_output = ""
        emitted = 0

        while True:
            if await request.is_disconnected():
                break
            if max_events is not None and emitted >= max_events:
                break

            try:
                response = await asyncio.to_thread(
                    _request_cao,
                    "GET",
                    f"/terminals/{terminal_id}/output",
                    {"mode": "last"},
                )
                body = await asyncio.to_thread(_response_json_or_text, response)
                output_text = ""
                if isinstance(body, dict):
                    output_text = str(body.get("output", "")).strip()

                if output_text and output_text != last_output:
                    last_output = output_text
                    emitted += 1
                    payload = json.dumps(
                        {
                            "terminal_id": terminal_id,
                            "output": output_text,
                            "at": int(time.time() * 1000),
                        },
                        ensure_ascii=False,
                    )
                    yield f"data: {payload}\n\n"
            except requests.exceptions.HTTPError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                if status_code == 404:
                    logger.info(
                        "SSE stream closed for %s: terminal not found upstream",
                        terminal_id,
                    )
                    break
                logger.warning("SSE stream read failed for %s: %s", terminal_id, exc)
            except Exception as exc:
                logger.warning("SSE stream read failed for %s: %s", terminal_id, exc)

            await asyncio.sleep(1.0)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.post("/console/agents/{receiver_id}/message")
async def send_message_to_agent(receiver_id: str, payload: InboxMessageRequest) -> Dict[str, Any]:
    sender_id = payload.sender_id or await asyncio.to_thread(_resolve_sender_id, receiver_id)
    if not sender_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot auto-resolve sender_id. Provide sender_id or ensure a supervisor exists.",
        )

    try:
        response = await asyncio.to_thread(
            _request_cao,
            "POST",
            f"/terminals/{receiver_id}/inbox/messages",
            {"sender_id": sender_id, "message": payload.message},
        )
        body = await asyncio.to_thread(_response_json_or_text, response)
        return {
            "ok": True,
            "receiver_id": receiver_id,
            "sender_id": sender_id,
            "result": body,
        }
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to send inbox message: {exc}")


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_to_cao(request: Request, path: str) -> Response:
    """
    Proxy all requests to the cao-server.
    This acts as a middleware layer between the frontend and the actual CAO API.
    """
    # Construct the upstream URL
    upstream_url = f"{CAO_SERVER_URL}/{path}"
    request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex

    # Forward query parameters
    if request.url.query:
        upstream_url += f"?{request.url.query}"

    # Prepare headers
    headers = {"X-Request-Id": request_id}
    if request.headers.get("content-type"):
        headers["Content-Type"] = request.headers["content-type"]
    if request.headers.get("authorization"):
        headers["Authorization"] = request.headers["authorization"]

    # Get request body if present
    body = None
    if request.method in ["POST", "PUT", "PATCH"]:
        try:
            body = await request.body()
        except Exception:
            pass

    try:
        logger.info(
            "Proxying request id=%s method=%s path=/%s upstream=%s",
            request_id,
            request.method,
            path,
            upstream_url,
        )

        # Make request to cao-server
        response = await asyncio.to_thread(
            requests.request,
            method=request.method,
            url=upstream_url,
            headers=headers,
            data=body,
            timeout=30,
        )

        # Return the response from cao-server
        return Response(
            content=response.content,
            status_code=response.status_code,
            headers={**dict(response.headers), "X-Request-Id": request_id},
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"Error proxying request to cao-server: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to reach cao-server: {str(e)}",
        )


if CONTROL_PANEL_STATIC_DIR.exists() and CONTROL_PANEL_STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(CONTROL_PANEL_STATIC_DIR), html=True), name="console-ui")
else:
    logger.warning(
        "Control panel static directory not found: %s. Frontend UI will be unavailable.",
        CONTROL_PANEL_STATIC_DIR,
    )


def main() -> None:
    """Run the control panel server."""
    import uvicorn

    logging.basicConfig(level=logging.INFO)
    logger.info(f"Starting CAO Control Panel server on {CONTROL_PANEL_HOST}:{CONTROL_PANEL_PORT}")
    logger.info(f"Proxying requests to cao-server at {CAO_SERVER_URL}")

    uvicorn.run(
        app,
        host=CONTROL_PANEL_HOST,
        port=CONTROL_PANEL_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()

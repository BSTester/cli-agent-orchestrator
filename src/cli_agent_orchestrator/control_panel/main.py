"""Control Panel FastAPI server - middleware layer between frontend and cao-server."""

import logging
import os
import re
import secrets
import sqlite3
import subprocess
import asyncio
import json
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import requests
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from cli_agent_orchestrator.constants import (
    API_BASE_URL,
    DATABASE_FILE,
    DB_DIR,
    LOCAL_AGENT_STORE_DIR,
)

logger = logging.getLogger(__name__)

# Control panel server configuration
CONTROL_PANEL_HOST = os.getenv("CONTROL_PANEL_HOST", "localhost")
CONTROL_PANEL_PORT = int(os.getenv("CONTROL_PANEL_PORT", "8000"))

# CAO server URL (the actual backend)
CAO_SERVER_URL = os.getenv("CAO_SERVER_URL", API_BASE_URL)
CONSOLE_PASSWORD = os.getenv("CAO_CONSOLE_PASSWORD", "admin")
SESSION_COOKIE_NAME = "cao_console_session"
SESSION_TTL_SECONDS = int(os.getenv("CAO_CONSOLE_SESSION_TTL_SECONDS", "43200"))

# CORS origins for frontend
CONTROL_PANEL_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

BUILTIN_AGENT_PROFILES = ("code_supervisor", "developer", "reviewer")
TASK_TITLE_MAX_LEN = 48
TASK_TITLE_FALLBACK_LEN = 20

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
        if LOCAL_AGENT_STORE_DIR.exists():
            for child in LOCAL_AGENT_STORE_DIR.iterdir():
                if child.is_file() and child.suffix == ".md":
                    names.add(child.stem)
    except Exception as exc:
        logger.warning("Failed to list local agent profiles: %s", exc)

    return sorted(names)


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

    LOCAL_AGENT_STORE_DIR.mkdir(parents=True, exist_ok=True)
    profile_path = LOCAL_AGENT_STORE_DIR / f"{normalized_name}.md"

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
    return LOCAL_AGENT_STORE_DIR / f"{normalized_name}.md"


_init_organization_db()


class LoginRequest(BaseModel):
    password: str = Field(min_length=1)


class AgentMessageRequest(BaseModel):
    message: str = Field(min_length=1)


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
    team_alias: Optional[str] = None
    agent_alias: Optional[str] = None


class AgentProfileCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)
    provider: Optional[str] = None


class AgentProfileUpdateRequest(BaseModel):
    content: str = Field(min_length=1)


class ConsoleCreateScheduledTaskRequest(BaseModel):
    flow_content: Optional[str] = None
    flow_name: Optional[str] = None
    file_name: Optional[str] = None
    leader_id: Optional[str] = None


def _console_flow_dir() -> Path:
    flow_dir = DB_DIR / "console_flows"
    flow_dir.mkdir(parents=True, exist_ok=True)
    return flow_dir


def _list_console_flow_files() -> List[Dict[str, Any]]:
    flow_dir = _console_flow_dir()
    files: List[Dict[str, Any]] = []
    for file_path in sorted(flow_dir.glob("*.md")):
        files.append(
            {
                "file_name": file_path.name,
                "flow_name": file_path.stem,
                "file_path": str(file_path),
            }
        )
    return files


def _resolve_console_flow_file(file_name: str) -> Path:
    normalized_name = file_name.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="file_name cannot be empty")

    # Only allow selecting files by basename from the managed flow directory.
    if Path(normalized_name).name != normalized_name:
        raise HTTPException(status_code=400, detail="Invalid file_name")

    if not re.fullmatch(r"[A-Za-z0-9_.-]+", normalized_name):
        raise HTTPException(status_code=400, detail="Invalid file_name")

    if not normalized_name.endswith(".md"):
        normalized_name = f"{normalized_name}.md"

    flow_path = _console_flow_dir() / normalized_name
    if not flow_path.exists():
        raise HTTPException(status_code=404, detail=f"Flow file not found: {normalized_name}")

    return flow_path


def _extract_flow_name_from_content(flow_content: str) -> Optional[str]:
    match = re.search(r"^name\s*:\s*([A-Za-z0-9_-]+)\s*$", flow_content, flags=re.MULTILINE)
    if match:
        return match.group(1)
    return None


def _save_flow_content_to_file(flow_content: str, flow_name: Optional[str]) -> Path:
    content = flow_content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Flow content cannot be empty")

    extracted_name = _extract_flow_name_from_content(content)
    normalized_name = (flow_name or extracted_name or "").strip()
    if not normalized_name:
        normalized_name = f"flow-{uuid.uuid4().hex[:8]}"

    if not re.fullmatch(r"[A-Za-z0-9_-]+", normalized_name):
        raise HTTPException(
            status_code=400,
            detail="Invalid flow name. Use letters, numbers, underscore, or hyphen.",
        )

    flow_dir = _console_flow_dir()
    flow_path = flow_dir / f"{normalized_name}.md"
    flow_path.write_text(content + "\n", encoding="utf-8")
    return flow_path


def _overwrite_console_flow_file(flow_path: Path, flow_content: str) -> Path:
    content = flow_content.strip()
    if not content:
        raise HTTPException(status_code=400, detail="Flow content cannot be empty")
    flow_path.write_text(content + "\n", encoding="utf-8")
    return flow_path


def _is_instant_task_status(status_value: Optional[str]) -> bool:
    normalized = (status_value or "").strip().lower()
    if not normalized:
        return False
    return normalized not in {"idle", "completed", "unknown", "stopped", "exited", "failed"}


def _normalize_flow_item(flow_item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": str(flow_item.get("name", "")),
        "file_path": str(flow_item.get("file_path", "")),
        "schedule": str(flow_item.get("schedule", "")),
        "agent_profile": str(flow_item.get("agent_profile", "")),
        "provider": str(flow_item.get("provider", "")),
        "script": str(flow_item.get("script", "")),
        "enabled": bool(flow_item.get("enabled", False)),
        "last_run": flow_item.get("last_run"),
        "next_run": flow_item.get("next_run"),
    }


def _cleanup_expired_sessions() -> None:
    now = time.time()
    expired_tokens = [token for token, expires_at in _sessions.items() if expires_at <= now]
    for token in expired_tokens:
        _sessions.pop(token, None)


def _session_expires_at(token: str) -> Optional[float]:
    _cleanup_expired_sessions()
    return _sessions.get(token)


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

    leaders = [terminal for terminal in terminals if terminal.get("is_main")]
    leader_ids = {str(terminal.get("id", "")) for terminal in leaders}
    for leader_id in teams_from_db:
        if leader_id in leader_ids:
            continue
        team_leader = terminals_by_id.get(leader_id)
        if not team_leader:
            continue
        team_leader_copy = dict(team_leader)
        team_leader_copy["is_main"] = True
        team_leader_copy["team_type"] = "independent_worker_team"
        leaders.append(team_leader_copy)
        leader_ids.add(leader_id)

    workers = [
        terminal
        for terminal in terminals
        if str(terminal.get("id", "")) not in leader_ids and not terminal.get("is_main")
    ]
    worker_ids = {
        str(worker.get("id", "")) for worker in workers if isinstance(worker.get("id"), str)
    }
    links_from_db = _list_worker_links()
    team_aliases = _list_team_aliases()
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
    if path == "/health" or path.startswith("/auth/"):
        return await call_next(request)

    if not _is_authenticated(request):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)

    return await call_next(request)


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint for the control panel."""
    try:
        # Also check if cao-server is reachable
        response = requests.get(f"{CAO_SERVER_URL}/health", timeout=5)
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


@app.get("/auth/me")
async def me(request: Request) -> Dict[str, Any]:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    expires_at = _session_expires_at(token) if token else None
    return {
        "authenticated": expires_at is not None,
        "session_expires_at": int(expires_at) if expires_at else None,
    }


@app.get("/console/overview")
async def console_overview() -> Dict[str, Any]:
    try:
        terminals = _get_terminals_from_sessions()
        provider_counts = Counter(str(t.get("provider", "unknown")) for t in terminals)
        status_counts = Counter(str(t.get("status", "unknown")) for t in terminals)
        profile_counts = Counter(str(t.get("agent_profile", "unknown")) for t in terminals)
        main_agents = [t for t in terminals if t.get("is_main")]
        uptime_seconds = int((datetime.now(timezone.utc) - _service_started_at).total_seconds())

        return {
            "uptime_seconds": uptime_seconds,
            "agents_total": len(terminals),
            "main_agents_total": len(main_agents),
            "worker_agents_total": len(terminals) - len(main_agents),
            "provider_counts": dict(provider_counts),
            "status_counts": dict(status_counts),
            "profile_counts": dict(profile_counts),
            "main_agents": main_agents,
        }
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch CAO data: {exc}")


@app.get("/console/agents")
async def console_agents() -> Dict[str, Any]:
    try:
        terminals = _get_terminals_from_sessions()
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
        terminals = _get_terminals_from_sessions()
        organization = _build_organization(terminals)
        return {
            "leaders_total": len(organization["leaders"]),
            "workers_total": len(organization["workers"]),
            **organization,
        }
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch organization: {exc}")


@app.get("/console/tasks")
async def console_tasks() -> Dict[str, Any]:
    try:
        terminals = _get_terminals_from_sessions()
        organization = _build_organization(terminals)
        terminal_ids = [str(item.get("id", "")) for item in terminals if isinstance(item, dict)]
        latest_task_titles = _list_latest_task_titles(terminal_ids)

        flows_response = _request_cao("GET", "/flows")
        flow_items = _response_json_or_text(flows_response)
        if not isinstance(flow_items, list):
            flow_items = []

        flow_team_links = _list_flow_team_links()
        flows_by_leader: Dict[str, List[Dict[str, Any]]] = {}
        unassigned_flows: List[Dict[str, Any]] = []

        for raw_flow in flow_items:
            if not isinstance(raw_flow, dict):
                continue
            flow = _normalize_flow_item(raw_flow)
            flow_name = flow["name"]
            leader_id = flow_team_links.get(flow_name)
            if leader_id:
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

    if file_name:
        flow_path = _resolve_console_flow_file(file_name)
        if flow_content:
            flow_path = _overwrite_console_flow_file(flow_path, flow_content)
    elif flow_content:
        flow_path = _save_flow_content_to_file(flow_content, payload.flow_name)
    else:
        raise HTTPException(status_code=400, detail="Provide either file_name or flow_content")

    body = {"file_path": str(flow_path)}

    try:
        response = _request_cao("POST", "/flows", json_body=body)
        created_flow = _response_json_or_text(response)
        if not isinstance(created_flow, dict):
            raise HTTPException(status_code=500, detail="Invalid flow creation response")

        flow_name = str(created_flow.get("name", ""))
        if not flow_name:
            raise HTTPException(status_code=500, detail="Flow name missing in response")

        leader_id = payload.leader_id.strip() if payload.leader_id else None
        _set_flow_team_link(flow_name, leader_id)
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
    return {"files": _list_console_flow_files()}


@app.get("/console/tasks/scheduled/files/{file_name}")
async def console_get_scheduled_task_file(file_name: str) -> Dict[str, Any]:
    flow_path = _resolve_console_flow_file(file_name)
    content = flow_path.read_text(encoding="utf-8")
    return {
        "file_name": flow_path.name,
        "flow_name": flow_path.stem,
        "file_path": str(flow_path),
        "content": content,
    }


@app.post("/console/tasks/scheduled/{flow_name}/run")
async def console_run_scheduled_task(flow_name: str) -> Dict[str, Any]:
    try:
        response = _request_cao("POST", f"/flows/{flow_name}/run")
        result = _response_json_or_text(response)
        return {"ok": True, "result": result}
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to run scheduled task: {exc}")


@app.post("/console/tasks/scheduled/{flow_name}/enable")
async def console_enable_scheduled_task(flow_name: str) -> Dict[str, Any]:
    try:
        response = _request_cao("POST", f"/flows/{flow_name}/enable")
        result = _response_json_or_text(response)
        return {"ok": True, "result": result}
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to enable scheduled task: {exc}")


@app.post("/console/tasks/scheduled/{flow_name}/disable")
async def console_disable_scheduled_task(flow_name: str) -> Dict[str, Any]:
    try:
        response = _request_cao("POST", f"/flows/{flow_name}/disable")
        result = _response_json_or_text(response)
        return {"ok": True, "result": result}
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to disable scheduled task: {exc}")


@app.delete("/console/tasks/scheduled/{flow_name}")
async def console_delete_scheduled_task(flow_name: str) -> Dict[str, Any]:
    try:
        response = _request_cao("DELETE", f"/flows/{flow_name}")
        result = _response_json_or_text(response)
        _remove_flow_team_link(flow_name)
        return {"ok": True, "result": result}
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to delete scheduled task: {exc}")


@app.get("/console/agent-profiles")
async def console_agent_profiles() -> Dict[str, Any]:
    return {"profiles": _list_available_agent_profiles()}


@app.post("/console/agent-profiles")
async def console_create_agent_profile(payload: AgentProfileCreateRequest) -> Dict[str, Any]:
    created_path = _create_local_agent_profile(
        name=payload.name,
        description=payload.description,
        system_prompt=payload.system_prompt,
        provider=payload.provider,
    )
    return {
        "ok": True,
        "profile": payload.name.strip(),
        "file_path": str(created_path),
    }


@app.get("/console/agent-profiles/{profile_name}")
async def console_get_agent_profile(profile_name: str) -> Dict[str, Any]:
    profile_path = _profile_file_path(profile_name)
    if not profile_path.exists():
        raise HTTPException(status_code=404, detail="Agent profile not found")

    return {
        "profile": profile_name,
        "file_path": str(profile_path),
        "content": profile_path.read_text(encoding="utf-8"),
    }


@app.put("/console/agent-profiles/{profile_name}")
async def console_update_agent_profile(
    profile_name: str,
    payload: AgentProfileUpdateRequest,
) -> Dict[str, Any]:
    profile_path = _profile_file_path(profile_name)
    if not profile_path.exists():
        raise HTTPException(status_code=404, detail="Agent profile not found")

    profile_path.write_text(payload.content, encoding="utf-8")
    return {"ok": True, "profile": profile_name, "file_path": str(profile_path)}


@app.post("/console/agent-profiles/{profile_name}/install")
async def console_install_agent_profile(profile_name: str) -> Dict[str, Any]:
    profile_path = _profile_file_path(profile_name)
    if not profile_path.exists():
        raise HTTPException(status_code=404, detail="Agent profile not found")

    try:
        process = subprocess.run(
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


@app.post("/console/organization/link")
async def console_link_worker(payload: OrgLinkRequest) -> Dict[str, Any]:
    worker_id = payload.worker_id.strip()
    leader_id = payload.leader_id.strip() if payload.leader_id else None

    try:
        worker_response = _request_cao("GET", f"/terminals/{worker_id}")
        worker_terminal = _response_json_or_text(worker_response)
        if not isinstance(worker_terminal, dict):
            raise HTTPException(status_code=400, detail="Invalid worker terminal")
        worker_profile = str(worker_terminal.get("agent_profile", "")).lower()
        if "supervisor" in worker_profile:
            raise HTTPException(status_code=400, detail="worker_id cannot be a main agent")

        if leader_id:
            leader_response = _request_cao("GET", f"/terminals/{leader_id}")
            leader_terminal = _response_json_or_text(leader_response)
            if not isinstance(leader_terminal, dict):
                raise HTTPException(status_code=400, detail="Invalid leader terminal")
            leader_profile = str(leader_terminal.get("agent_profile", "")).lower()
            if "supervisor" not in leader_profile:
                raise HTTPException(status_code=400, detail="leader_id must be a main agent")
            _register_team(leader_id)
            _set_worker_link(worker_id, leader_id)
        else:
            _remove_worker_link(worker_id)

        return {"ok": True, "worker_id": worker_id, "leader_id": leader_id}
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to link organization: {exc}")


@app.post("/console/organization/create")
async def console_create_org_agent(payload: OrgCreateRequest) -> Dict[str, Any]:
    params: Dict[str, str] = {"agent_profile": payload.agent_profile}
    if payload.provider:
        params["provider"] = payload.provider
    if payload.working_directory:
        params["working_directory"] = payload.working_directory

    try:
        if payload.role_type == "main":
            created_response = _request_cao("POST", "/sessions", params=params)
            created_agent = _response_json_or_text(created_response)
            if isinstance(created_agent, dict) and isinstance(created_agent.get("id"), str):
                leader_id = created_agent["id"]
                _register_team(leader_id)
                if payload.team_alias:
                    _set_team_alias(leader_id, payload.team_alias)
                if payload.agent_alias:
                    _set_agent_alias(leader_id, payload.agent_alias)
            return {
                "ok": True,
                "role_type": payload.role_type,
                "leader_id": None,
                "agent": created_agent,
            }

        if payload.leader_id:
            leader_response = _request_cao("GET", f"/terminals/{payload.leader_id}")
            leader_terminal = _response_json_or_text(leader_response)
            if not isinstance(leader_terminal, dict):
                raise HTTPException(status_code=400, detail="Invalid leader_id")
            session_name = leader_terminal.get("session_name")
            if not session_name:
                raise HTTPException(status_code=400, detail="leader has no session")

            created_response = _request_cao(
                "POST",
                f"/sessions/{session_name}/terminals",
                params=params,
            )
            created_agent = _response_json_or_text(created_response)
            if isinstance(created_agent, dict) and isinstance(created_agent.get("id"), str):
                _register_team(payload.leader_id)
                worker_id = created_agent["id"]
                _set_worker_link(worker_id, payload.leader_id)
                if payload.agent_alias:
                    _set_agent_alias(worker_id, payload.agent_alias)
            return {
                "ok": True,
                "role_type": payload.role_type,
                "leader_id": payload.leader_id,
                "agent": created_agent,
            }

        created_response = _request_cao("POST", "/sessions", params=params)
        created_agent = _response_json_or_text(created_response)
        created_agent_id = created_agent.get("id") if isinstance(created_agent, dict) else None
        if isinstance(created_agent_id, str):
            _register_team(created_agent_id)
            if payload.team_alias:
                _set_team_alias(created_agent_id, payload.team_alias)
            if payload.agent_alias:
                _set_agent_alias(created_agent_id, payload.agent_alias)
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


@app.post("/console/agents/{terminal_id}/input")
async def send_input_to_agent(terminal_id: str, payload: AgentMessageRequest) -> Dict[str, Any]:
    try:
        response = _request_cao(
            "POST",
            f"/terminals/{terminal_id}/input",
            params={"message": payload.message},
        )
        body = _response_json_or_text(response)
        return {"ok": True, "terminal_id": terminal_id, "result": body}
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to send input: {exc}")


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
                response = _request_cao(
                    "GET",
                    f"/terminals/{terminal_id}/output",
                    params={"mode": "last"},
                )
                body = _response_json_or_text(response)
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
    sender_id = payload.sender_id or _resolve_sender_id(receiver_id)
    if not sender_id:
        raise HTTPException(
            status_code=400,
            detail="Cannot auto-resolve sender_id. Provide sender_id or ensure a supervisor exists.",
        )

    try:
        response = _request_cao(
            "POST",
            f"/terminals/{receiver_id}/inbox/messages",
            params={"sender_id": sender_id, "message": payload.message},
        )
        body = _response_json_or_text(response)
        return {
            "ok": True,
            "receiver_id": receiver_id,
            "sender_id": sender_id,
            "result": body,
        }
    except requests.exceptions.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Failed to send inbox message: {exc}")


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
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
        response = requests.request(
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

"""Helpers for persistent provider runtime configuration."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from cli_agent_orchestrator.constants import PROVIDER_RUNTIME_CONFIG_FILE

_DEFAULT_CONFIG: Dict[str, Any] = {
    "version": 1,
    "onboarding": {
        "dismissed": False,
        "dismissed_at": None,
        "completed_at": None,
    },
    "providers": {},
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _config_path() -> Path:
    return PROVIDER_RUNTIME_CONFIG_FILE


def load_provider_runtime_config() -> Dict[str, Any]:
    """Load the provider runtime config file, returning defaults on failure."""
    path = _config_path()
    if not path.exists():
        return deepcopy(_DEFAULT_CONFIG)

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return deepcopy(_DEFAULT_CONFIG)

    data = deepcopy(_DEFAULT_CONFIG)
    if isinstance(payload, dict):
        onboarding = payload.get("onboarding")
        providers = payload.get("providers")
        if isinstance(onboarding, dict):
            data["onboarding"].update(onboarding)
        if isinstance(providers, dict):
            data["providers"] = providers
        version = payload.get("version")
        if isinstance(version, int):
            data["version"] = version
    return data


def save_provider_runtime_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Persist provider runtime config and return the normalized payload."""
    data = deepcopy(_DEFAULT_CONFIG)
    if isinstance(config, dict):
        onboarding = config.get("onboarding")
        providers = config.get("providers")
        if isinstance(onboarding, dict):
            data["onboarding"].update(onboarding)
        if isinstance(providers, dict):
            data["providers"] = providers
        version = config.get("version")
        if isinstance(version, int):
            data["version"] = version

    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")
    return data


def get_provider_runtime_settings(provider_id: str) -> Dict[str, Any]:
    """Return stored settings for a provider id."""
    config = load_provider_runtime_config()
    providers = config.get("providers", {})
    payload = providers.get(provider_id)
    if isinstance(payload, dict):
        return payload
    return {}


def update_provider_runtime_settings(provider_id: str, values: Dict[str, Any]) -> Dict[str, Any]:
    """Merge provider settings into persisted config."""
    config = load_provider_runtime_config()
    providers = config.setdefault("providers", {})
    existing = providers.get(provider_id)
    current = dict(existing) if isinstance(existing, dict) else {}

    for key, value in values.items():
        if value is None:
            current.pop(key, None)
        else:
            current[key] = value

    current["updated_at"] = _utc_now_iso()
    providers[provider_id] = current
    save_provider_runtime_config(config)
    return current


def set_onboarding_state(
    *,
    dismissed: Optional[bool] = None,
    completed: Optional[bool] = None,
) -> Dict[str, Any]:
    """Update onboarding dismissal/completion markers."""
    config = load_provider_runtime_config()
    onboarding = config.setdefault("onboarding", {})

    if dismissed is not None:
        onboarding["dismissed"] = dismissed
        onboarding["dismissed_at"] = _utc_now_iso() if dismissed else None

    if completed is not None:
        onboarding["completed_at"] = _utc_now_iso() if completed else None
        if completed:
            onboarding["dismissed"] = True
            onboarding["dismissed_at"] = onboarding["completed_at"]

    save_provider_runtime_config(config)
    return onboarding

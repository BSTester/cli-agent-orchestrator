"""CLI Agent Orchestrator MCP Server implementation."""

import asyncio
import logging
import os
import subprocess
import time
from typing import Any, Dict, Optional, Tuple

import requests
from fastmcp import FastMCP
from pydantic import Field

from cli_agent_orchestrator.constants import API_BASE_URL, DEFAULT_PROVIDER, PROVIDERS
from cli_agent_orchestrator.mcp_server.models import HandoffResult
from cli_agent_orchestrator.models.terminal import TerminalStatus
from cli_agent_orchestrator.utils.agent_profiles import load_agent_profile
from cli_agent_orchestrator.utils.terminal import generate_session_name, wait_until_terminal_status

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT_SECONDS = 15
REQUEST_RETRY_ATTEMPTS = 3
REQUEST_RETRY_BACKOFF_SECONDS = 0.5
WORK_AGENT_CREATE_RETRY_ATTEMPTS = 3
PROVIDER_READY_TIMEOUT_SECONDS = 120.0
PROVIDER_READY_STATUSES = {TerminalStatus.IDLE, TerminalStatus.COMPLETED}
ASSIGN_POST_READY_STABILIZATION_SECONDS = 2.0
ASSIGN_SUBMIT_CONFIRMATION_SECONDS = 3.0
ASSIGN_SUBMIT_CONFIRMATION_POLL_SECONDS = 0.5
HANDOFF_OUTPUT_SETTLE_POLLING_SECONDS = 1.0
HANDOFF_OUTPUT_SETTLE_MAX_SECONDS = 30.0

# Environment variable to enable/disable working_directory parameter
ENABLE_WORKING_DIRECTORY = os.getenv("CAO_ENABLE_WORKING_DIRECTORY", "false").lower() == "true"

# Create MCP server
mcp = FastMCP(
    "cao-mcp-server",
    instructions="""
    # CLI Agent Orchestrator MCP Server

    This server provides tools to facilitate terminal delegation within CLI Agent Orchestrator sessions.

    ## Best Practices

    - Use specific agent profiles and providers
    - Provide clear and concise messages
    - Ensure you're running within a CAO terminal (CAO_TERMINAL_ID must be set)
    """,
)


def _current_terminal_id() -> str:
    """Resolve current terminal ID from env or tmux environment."""
    env_id = os.environ.get("CAO_TERMINAL_ID")
    if env_id:
        return env_id

    try:
        result = subprocess.run(
            ["tmux", "show-environment", "CAO_TERMINAL_ID"],
            capture_output=True,
            text=True,
            check=False,
        )
        output = (result.stdout or "").strip()
        if output.startswith("CAO_TERMINAL_ID="):
            candidate = output.split("=", 1)[1].strip()
            if candidate:
                return candidate
    except Exception as exc:
        logger.debug("Failed to resolve CAO_TERMINAL_ID from tmux: %s", exc)

    raise ValueError("CAO_TERMINAL_ID not set")


def _inject_terminal_id(message: str) -> str:
    """Replace common terminal ID placeholders in outgoing messages."""
    try:
        terminal_id = _current_terminal_id()
    except ValueError:
        return message

    replacements = [
        "${CAO_TERMINAL_ID}",
        "${process.env.CAO_TERMINAL_ID}",
        "{{CAO_TERMINAL_ID}}",
        "{{ CAO_TERMINAL_ID }}",
        "{{process.env.CAO_TERMINAL_ID}}",
    ]

    for placeholder in replacements:
        message = message.replace(placeholder, terminal_id)

    return message


def _request_with_retry(
    method: str, url: str, retry_attempts: int = REQUEST_RETRY_ATTEMPTS, **kwargs: Any
) -> requests.Response:
    """Send HTTP request with simple retry for transient connection errors."""
    timeout = kwargs.pop("timeout", REQUEST_TIMEOUT_SECONDS)
    last_error: Optional[Exception] = None

    for attempt in range(1, retry_attempts + 1):
        try:
            response = requests.request(method=method, url=url, timeout=timeout, **kwargs)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as exc:
            last_error = exc
            if attempt == retry_attempts:
                break
            time.sleep(REQUEST_RETRY_BACKOFF_SECONDS * attempt)

    if last_error is None:
        raise RuntimeError("Request failed without exception details")
    raise last_error


def _control_panel_base_url() -> str:
    port = int(os.getenv("CONTROL_PANEL_PORT", "8000"))
    return f"http://localhost:{port}"


def _sync_worker_terminal_metadata(worker_terminal_id: str, agent_profile: str) -> None:
    """Best-effort sync of worker alias and org link into control panel state."""
    try:
        _request_with_retry(
            "POST",
            f"{_control_panel_base_url()}/console/internal/agent-alias/auto-set",
            json={"terminal_id": worker_terminal_id, "agent_profile": agent_profile},
            retry_attempts=1,
            timeout=5,
        )
    except Exception as exc:
        logger.warning(
            "Failed to auto-set agent alias for worker %s (%s): %s",
            worker_terminal_id,
            agent_profile,
            exc,
        )

    try:
        leader_terminal_id = _current_terminal_id()
    except ValueError:
        return

    if not leader_terminal_id or leader_terminal_id == worker_terminal_id:
        return

    try:
        _request_with_retry(
            "POST",
            f"{_control_panel_base_url()}/console/internal/organization/link",
            json={"worker_id": worker_terminal_id, "leader_id": leader_terminal_id},
            retry_attempts=1,
            timeout=5,
        )
    except Exception as exc:
        logger.warning(
            "Failed to link worker %s to leader %s in organization: %s",
            worker_terminal_id,
            leader_terminal_id,
            exc,
        )


def _build_handoff_message(
    provider: str,
    supervisor_terminal_id: str,
    user_message: str,
) -> str:
    """Build a blocking handoff message that keeps the worker terminal online."""
    base_prefix = (
        f"[CAO Handoff] Supervisor terminal ID: {supervisor_terminal_id}. "
        "This is a blocking handoff. The orchestrator will automatically capture your "
        "response when you finish. Complete the task, present your deliverables, and "
        "remain online in this terminal. Do NOT send /exit or /quit unless explicitly "
        "instructed. "
    )

    if provider == "codex":
        provider_specific = (
            "Do NOT use send_message to notify the supervisor unless explicitly needed. "
        )
    else:
        provider_specific = ""

    return f"{base_prefix}{provider_specific}\n\n{user_message}"


def _create_terminal_with_retry(
    agent_profile: str,
    working_directory: Optional[str] = None,
    provider: Optional[str] = None,
) -> Tuple[str, str]:
    """Create terminal without retry to avoid duplicate workers."""
    return _create_terminal(agent_profile, working_directory=working_directory, provider=provider)


def _create_terminal(
    agent_profile: str,
    working_directory: Optional[str] = None,
    provider: Optional[str] = None,
) -> Tuple[str, str]:
    """Create a new terminal with the specified agent profile.

    Args:
        agent_profile: Agent profile for the terminal
        working_directory: Optional working directory for the terminal
        provider: Optional provider override

    Returns:
        Tuple of (terminal_id, provider)

    Raises:
        Exception: If terminal creation fails
    """
    inherited_provider = DEFAULT_PROVIDER
    resolved_provider = provider

    if resolved_provider is not None and resolved_provider.strip() == "":
        resolved_provider = None

    if resolved_provider and resolved_provider not in PROVIDERS:
        raise ValueError(
            f"Invalid provider '{resolved_provider}'. Available providers: {', '.join(PROVIDERS)}"
        )

    # Get current terminal ID from environment
    try:
        current_terminal_id = _current_terminal_id()
    except ValueError:
        current_terminal_id = None

    if current_terminal_id:
        # Get terminal metadata via API
        response = _request_with_retry("GET", f"{API_BASE_URL}/terminals/{current_terminal_id}")
        terminal_metadata = response.json()

        inherited_provider = terminal_metadata["provider"]
        session_name = terminal_metadata["session_name"]

        # If no working_directory specified, get conductor's current directory
        if working_directory is None:
            try:
                response = _request_with_retry(
                    "GET",
                    f"{API_BASE_URL}/terminals/{current_terminal_id}/working-directory",
                )
                working_directory = response.json().get("working_directory")
                logger.info(f"Inherited working directory from conductor: {working_directory}")
            except Exception as e:
                logger.warning(
                    f"Error fetching conductor's working directory: {e}, will use server default"
                )

        if resolved_provider is None:
            try:
                profile = load_agent_profile(agent_profile)
                if profile.provider is not None:
                    resolved_provider = profile.provider.value
            except Exception:
                pass

        if resolved_provider is None:
            resolved_provider = inherited_provider

        # Try to reuse an existing idle terminal with the same profile/provider to avoid
        # spawning duplicates when a worker already exists.
        try:
            list_response = _request_with_retry(
                "GET",
                f"{API_BASE_URL}/sessions/{session_name}/terminals",
                retry_attempts=1,
            )
            for terminal_info in list_response.json():
                if (
                    terminal_info.get("agent_profile") == agent_profile
                    and terminal_info.get("provider") == resolved_provider
                ):
                    status_resp = _request_with_retry(
                        "GET",
                        f"{API_BASE_URL}/terminals/{terminal_info['id']}",
                        retry_attempts=1,
                    )
                    if status_resp.json().get("status") == TerminalStatus.IDLE.value:
                        logger.info(
                            "Reusing idle terminal %s for agent_profile=%s provider=%s",
                            terminal_info["id"],
                            agent_profile,
                            resolved_provider,
                        )
                        return terminal_info["id"], resolved_provider
        except Exception as exc:
            logger.warning("Failed to reuse idle terminal, will create new one: %s", exc)

        # Create new terminal in existing session - always pass working_directory
        params: Dict[str, Any] = {"agent_profile": agent_profile}
        if resolved_provider is not None and (
            provider is not None or resolved_provider != DEFAULT_PROVIDER
        ):
            params["provider"] = resolved_provider
        if working_directory:
            params["working_directory"] = working_directory

        response = _request_with_retry(
            "POST",
            f"{API_BASE_URL}/sessions/{session_name}/terminals",
            params=params,
            retry_attempts=1,
        )
        terminal = response.json()
    else:
        # Create new session with terminal
        session_name = generate_session_name()
        if resolved_provider is None:
            try:
                profile = load_agent_profile(agent_profile)
                if profile.provider is not None:
                    resolved_provider = profile.provider.value
            except Exception:
                pass
        if resolved_provider is None:
            resolved_provider = DEFAULT_PROVIDER

        params: Dict[str, Any] = {
            "agent_profile": agent_profile,
            "session_name": session_name,
        }
        if resolved_provider is not None and (
            provider is not None or resolved_provider != DEFAULT_PROVIDER
        ):
            params["provider"] = resolved_provider
        if working_directory:
            params["working_directory"] = working_directory

        response = _request_with_retry(
            "POST", f"{API_BASE_URL}/sessions", params=params, retry_attempts=1
        )
        terminal = response.json()

    if resolved_provider is None:
        resolved_provider = terminal.get("provider", DEFAULT_PROVIDER)

    return terminal["id"], resolved_provider


def _find_existing_assign_terminal(
    agent_profile: str, provider: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    """Find an existing terminal in the current session for assign."""
    resolved_provider = provider

    if resolved_provider is not None and resolved_provider.strip() == "":
        resolved_provider = None

    if resolved_provider and resolved_provider not in PROVIDERS:
        raise ValueError(
            f"Invalid provider '{resolved_provider}'. Available providers: {', '.join(PROVIDERS)}"
        )

    try:
        current_terminal_id = _current_terminal_id()
    except ValueError:
        return None, resolved_provider

    try:
        metadata_resp = _request_with_retry("GET", f"{API_BASE_URL}/terminals/{current_terminal_id}")
        terminal_metadata = metadata_resp.json()
        session_name = terminal_metadata["session_name"]
        inherited_provider = terminal_metadata["provider"]
    except Exception as exc:
        logger.warning("Failed to load supervisor terminal metadata, skip reuse: %s", exc)
        return None, resolved_provider

    if resolved_provider is None:
        try:
            profile = load_agent_profile(agent_profile)
            if profile.provider is not None:
                resolved_provider = profile.provider.value
        except Exception:
            pass

    if resolved_provider is None:
        resolved_provider = inherited_provider

    try:
        list_response = _request_with_retry(
            "GET",
            f"{API_BASE_URL}/sessions/{session_name}/terminals",
            retry_attempts=1,
        )
        for terminal_info in list_response.json():
            if terminal_info.get("id") == current_terminal_id:
                continue
            if terminal_info.get("agent_profile") != agent_profile:
                continue
            if terminal_info.get("provider") != resolved_provider:
                continue

            candidate_id = terminal_info.get("id")
            if not candidate_id:
                continue

            try:
                status_resp = _request_with_retry(
                    "GET",
                    f"{API_BASE_URL}/terminals/{candidate_id}",
                    retry_attempts=1,
                )
                if status_resp.json().get("status") == TerminalStatus.ERROR.value:
                    continue
            except Exception:
                logger.debug("Status check failed for terminal %s; attempting reuse", candidate_id)

            logger.info(
                "Reusing existing terminal %s for agent_profile=%s provider=%s",
                candidate_id,
                agent_profile,
                resolved_provider,
            )
            return candidate_id, terminal_info.get("provider", resolved_provider)
    except Exception as exc:
        logger.warning("Failed to query existing terminals for reuse: %s", exc)

    return None, resolved_provider


def _send_direct_input(terminal_id: str, message: str) -> None:
    """Send input directly to a terminal (bypasses inbox).

    Args:
        terminal_id: Terminal ID
        message: Message to send

    Raises:
        Exception: If sending fails
    """
    _request_with_retry(
        "POST", f"{API_BASE_URL}/terminals/{terminal_id}/input", params={"message": message}
    )


def _send_special_key(terminal_id: str, key: str) -> None:
    """Send a tmux special key to a terminal via API."""
    _request_with_retry(
        "POST",
        f"{API_BASE_URL}/terminals/{terminal_id}/special-key",
        params={"key": key},
    )


def _confirm_assign_submission(terminal_id: str) -> None:
    """Ensure a freshly created worker actually consumed the first assign message.

    Some providers transiently report ready before the input box is fully focused.
    In that case the first pasted message may appear in the UI without being submitted.
    If the terminal never leaves ready state shortly after the initial send, press Enter once
    to submit the already populated input.
    """
    deadline = time.time() + ASSIGN_SUBMIT_CONFIRMATION_SECONDS

    while time.time() < deadline:
        try:
            response = _request_with_retry(
                "GET",
                f"{API_BASE_URL}/terminals/{terminal_id}",
                retry_attempts=1,
            )
            status_value = str(response.json().get("status") or "").strip().lower()
        except Exception as exc:
            logger.warning(
                "Failed to confirm assign submission for terminal %s: %s",
                terminal_id,
                exc,
            )
            return

        if status_value not in {
            TerminalStatus.IDLE.value,
            TerminalStatus.COMPLETED.value,
        }:
            return

        time.sleep(ASSIGN_SUBMIT_CONFIRMATION_POLL_SECONDS)

    logger.info(
        "Assign terminal %s stayed in ready state after first send; sending extra Enter",
        terminal_id,
    )
    _send_special_key(terminal_id, "C-m")


def _send_to_inbox(receiver_id: str, message: str) -> Dict[str, Any]:
    """Send message to another terminal's inbox (queued delivery when IDLE).

    Args:
        receiver_id: Target terminal ID
        message: Message content

    Returns:
        Dict with message details

    Raises:
        ValueError: If CAO_TERMINAL_ID not set
        Exception: If API call fails
    """
    sender_id = _current_terminal_id()

    if not message.strip():
        raise ValueError("Message cannot be empty")

    response = _request_with_retry(
        "POST",
        f"{API_BASE_URL}/terminals/{receiver_id}/inbox/messages",
        params={"sender_id": sender_id, "message": message},
    )
    return response.json()


def _send_message_impl(receiver_id: str, message: str) -> Dict[str, Any]:
    """Implementation of send_message."""
    return _send_to_inbox(receiver_id, message)


def _looks_like_incomplete_handoff_output(output: str) -> bool:
    """Heuristic check for transient rendering/progress output.

    Some providers may transiently render UI/status text (e.g. "Generating...")
    while terminal status already appears completed.
    """
    normalized = output.strip().lower()
    if not normalized:
        return True

    transient_markers = (
        "generating...",
        "generating",
        "thinking...",
        "thinking",
        "processing...",
        "processing",
        "analyzing...",
        "analyzing",
        "working...",
        "working",
        "esc to interrupt",
    )
    return any(marker in normalized for marker in transient_markers)


def _fetch_stable_handoff_output(terminal_id: str, timeout_seconds: int) -> str:
    """Fetch handoff output and wait briefly for non-transient content."""
    settle_window = max(3.0, min(HANDOFF_OUTPUT_SETTLE_MAX_SECONDS, timeout_seconds / 4))
    deadline = time.time() + settle_window
    last_output = ""

    while True:
        response = _request_with_retry(
            "GET", f"{API_BASE_URL}/terminals/{terminal_id}/output", params={"mode": "last"}
        )
        output_data = response.json()
        output = str(output_data.get("output", "")).strip()
        if output:
            last_output = output

        if output and not _looks_like_incomplete_handoff_output(output):
            return output

        if time.time() >= deadline:
            return last_output

        time.sleep(HANDOFF_OUTPUT_SETTLE_POLLING_SECONDS)


# Implementation functions
async def _handoff_impl(
    agent_profile: str,
    message: str,
    timeout: int = 600,
    working_directory: Optional[str] = None,
    provider: Optional[str] = None,
) -> HandoffResult:
    """Implementation of handoff logic."""
    start_time = time.time()

    try:
        message = _inject_terminal_id(message)
        # Create terminal
        terminal_id, provider = _create_terminal_with_retry(
            agent_profile, working_directory=working_directory, provider=provider
        )

        # Wait for terminal to be ready (IDLE or COMPLETED) before sending
        # the handoff message. Accept COMPLETED in addition to IDLE because
        # providers that use an initial prompt flag process the system prompt
        # as the first user message and produce a response, reaching COMPLETED
        # without ever showing a bare IDLE state.
        # Both states indicate the provider is ready to accept input.
        #
        # Use a generous timeout (120s) because provider initialization can be
        # slow: shell warm-up (~5s), CLI startup with MCP server registration
        # (~10-30s), and API authentication (~5-10s). If the provider's own
        # initialize() timed out (60-90s), this acts as a fallback to catch
        # cases where the CLI starts slightly after the provider timeout.
        # Provider initialization can be slow (~15-45s depending on provider).
        if not wait_until_terminal_status(
            terminal_id,
            PROVIDER_READY_STATUSES,
            timeout=PROVIDER_READY_TIMEOUT_SECONDS,
        ):
            return HandoffResult(
                success=False,
                message=(
                    f"Terminal {terminal_id} did not reach ready status within "
                    f"{int(PROVIDER_READY_TIMEOUT_SECONDS)} seconds"
                ),
                output=None,
                terminal_id=terminal_id,
            )

        await asyncio.sleep(2)  # wait another 2s

        try:
            supervisor_id = _current_terminal_id()
        except ValueError:
            supervisor_id = "unknown"

        handoff_message = _build_handoff_message(provider, supervisor_id, message)

        _sync_worker_terminal_metadata(terminal_id, agent_profile)

        # Send message to terminal
        _send_direct_input(terminal_id, handoff_message)

        # Monitor until agent returns to IDLE state (task completed but terminal stays online)
        # Changed from COMPLETED to IDLE to keep worker agents online after task completion
        if not wait_until_terminal_status(
            terminal_id, TerminalStatus.IDLE, timeout=timeout, polling_interval=1.0
        ):
            return HandoffResult(
                success=False,
                message=f"Handoff timed out after {timeout} seconds",
                output=None,
                terminal_id=terminal_id,
            )

        # Get response with short stabilization polling to avoid returning
        # transient CLI rendering status (e.g. "Generating...")
        output = _fetch_stable_handoff_output(terminal_id, timeout)

        execution_time = time.time() - start_time

        return HandoffResult(
            success=True,
            message=f"Successfully handed off to {agent_profile} ({provider}) in {execution_time:.2f}s",
            output=output,
            terminal_id=terminal_id,
        )

    except Exception as e:
        return HandoffResult(
            success=False, message=f"Handoff failed: {str(e)}", output=None, terminal_id=None
        )


# Conditional tool registration based on environment variable
if ENABLE_WORKING_DIRECTORY:

    @mcp.tool()
    async def handoff(  # type: ignore[misc]
        agent_profile: str = Field(
            description='The agent profile to hand off to (e.g., "developer", "analyst")'
        ),
        message: str = Field(description="The message/task to send to the target agent"),
        timeout: int = Field(
            default=600,
            description="Maximum time to wait for the agent to complete the task (in seconds)",
            ge=1,
            le=3600,
        ),
        provider: Optional[str] = Field(
            default=None,
            description="Optional provider override for the target agent terminal",
        ),
        working_directory: Optional[str] = Field(
            default=None,
            description='Optional working directory where the agent should execute (e.g., "/path/to/workspace/src/Package")',
        ),
    ) -> HandoffResult:
        """Hand off a task to another agent via CAO terminal and wait for completion.

        This tool allows handing off tasks to other agents by creating a new terminal
        in the same session. It sends the message, waits for completion, and captures the output.

        ## Usage

        Use this tool to hand off tasks to another agent and wait for the results.
        The tool will:
        1. Create a new terminal with the specified agent profile and provider
        2. Set the working directory for the terminal (defaults to supervisor's cwd)
        3. Send the message to the terminal
        4. Monitor until completion
        5. Return the agent's response
        6. Leave the worker terminal running for reuse

        ## Working Directory

        - By default, agents start in the supervisor's current working directory
        - You can specify a custom directory via working_directory parameter
        - Directory must exist and be accessible

        ## Requirements

        - Must be called from within a CAO terminal (CAO_TERMINAL_ID environment variable)
        - Target session must exist and be accessible
        - If working_directory is provided, it must exist and be accessible

        Args:
            agent_profile: The agent profile for the new terminal
            message: The task/message to send
            timeout: Maximum wait time in seconds
            provider: Optional provider override
            working_directory: Optional directory path where agent should execute

        Returns:
            HandoffResult with success status, message, and agent output
        """
        return await _handoff_impl(
            agent_profile,
            message,
            timeout,
            working_directory=working_directory,
            provider=provider,
        )

else:

    @mcp.tool()
    async def handoff(  # type: ignore[misc]
        agent_profile: str = Field(
            description='The agent profile to hand off to (e.g., "developer", "analyst")'
        ),
        message: str = Field(description="The message/task to send to the target agent"),
        timeout: int = Field(
            default=600,
            description="Maximum time to wait for the agent to complete the task (in seconds)",
            ge=1,
            le=3600,
        ),
        provider: Optional[str] = Field(
            default=None,
            description="Optional provider override for the target agent terminal",
        ),
    ) -> HandoffResult:
        """Hand off a task to another agent via CAO terminal and wait for completion.

        This tool allows handing off tasks to other agents by creating a new terminal
        in the same session. It sends the message, waits for completion, and captures the output.

        ## Usage

        Use this tool to hand off tasks to another agent and wait for the results.
        The tool will:
        1. Create a new terminal with the specified agent profile and provider
        2. Send the message to the terminal (starts in supervisor's current directory)
        3. Monitor until completion
        4. Return the agent's response
        5. Leave the worker terminal running for reuse

        ## Requirements

        - Must be called from within a CAO terminal (CAO_TERMINAL_ID environment variable)
        - Target session must exist and be accessible

        Args:
            agent_profile: The agent profile for the new terminal
            message: The task/message to send
            timeout: Maximum wait time in seconds
            provider: Optional provider override

        Returns:
            HandoffResult with success status, message, and agent output
        """
        return await _handoff_impl(
            agent_profile, message, timeout, working_directory=None, provider=provider
        )


# Implementation function for assign
def _assign_impl(
    agent_profile: str,
    message: str,
    working_directory: Optional[str] = None,
    provider: Optional[str] = None,
) -> Dict[str, Any]:
    """Implementation of assign logic."""
    try:
        message = _inject_terminal_id(message)
        if not message.strip():
            return {
                "success": False,
                "terminal_id": None,
                "message": "Assignment failed: message cannot be empty",
            }

        terminal_id: Optional[str] = None
        resolved_provider: Optional[str] = None

        existing_terminal_id, resolved_provider = _find_existing_assign_terminal(
            agent_profile, provider=provider
        )

        if existing_terminal_id:
            terminal_id = existing_terminal_id
            _sync_worker_terminal_metadata(terminal_id, agent_profile)
        else:
            terminal_id, resolved_provider = _create_terminal_with_retry(
                agent_profile, working_directory=working_directory, provider=provider
            )

            if not wait_until_terminal_status(
                terminal_id,
                PROVIDER_READY_STATUSES,
                timeout=PROVIDER_READY_TIMEOUT_SECONDS,
            ):
                return {
                    "success": False,
                    "terminal_id": terminal_id,
                    "message": (
                        f"Assignment failed: terminal {terminal_id} did not become ready within "
                        f"{int(PROVIDER_READY_TIMEOUT_SECONDS)} seconds"
                    ),
                }

            # Newly created worker terminals may report ready slightly before the
            # interactive prompt fully stabilizes. Add a short delay to match
            # handoff behavior and avoid first-assignment input being ignored.
            time.sleep(ASSIGN_POST_READY_STABILIZATION_SECONDS)

            _sync_worker_terminal_metadata(terminal_id, agent_profile)

            _send_direct_input(terminal_id, message)
            _confirm_assign_submission(terminal_id)

            return {
                "success": True,
                "terminal_id": terminal_id,
                "message": (
                    f"Task assigned to {agent_profile} ({resolved_provider}) "
                    f"(terminal: {terminal_id})"
                ),
            }

        try:
            _send_to_inbox(terminal_id, message)
        except Exception as exc:
            logger.warning(
                "Inbox initial assignment failed for %s (%s); falling back to direct input",
                terminal_id,
                exc,
            )
            _send_direct_input(terminal_id, message)

        return {
            "success": True,
            "terminal_id": terminal_id,
            "message": (
                f"Task assigned to {agent_profile} ({resolved_provider}) "
                f"(terminal: {terminal_id})"
            ),
        }

    except Exception as e:
        return {"success": False, "terminal_id": None, "message": f"Assignment failed: {str(e)}"}


# Conditional tool registration for assign
if ENABLE_WORKING_DIRECTORY:

    @mcp.tool()
    async def assign(  # type: ignore[misc]
        agent_profile: str = Field(
            description='The agent profile for the worker agent (e.g., "developer", "analyst")'
        ),
        message: str = Field(
            min_length=1,
            description="The task message to send. Include callback instructions for the worker to send results back."
        ),
        provider: Optional[str] = Field(
            default=None,
            description="Optional provider override for the worker terminal",
        ),
        working_directory: Optional[str] = Field(
            default=None, description="Optional working directory where the agent should execute"
        ),
    ) -> Dict[str, Any]:
        """Assigns a task to another agent without blocking.

        In the message to the worker agent include instruction to send results back via send_message tool.
        **IMPORTANT**: The terminal id of each agent is available in environment variable CAO_TERMINAL_ID.
        When assigning, first find out your own CAO_TERMINAL_ID value, then include the terminal_id value in the message to the worker agent to allow callback.
        Example message: "Analyze the logs. When done, send results back to terminal ee3f93b3 using send_message tool."

        ## Working Directory

        - By default, agents start in the supervisor's current working directory
        - You can specify a custom directory via working_directory parameter
        - Directory must exist and be accessible

        Args:
            agent_profile: Agent profile for the worker terminal
            message: Task message (include callback instructions)
            provider: Optional provider override
            working_directory: Optional directory path where agent should execute

        Returns:
            Dict with success status, worker terminal_id, and message
        """
        return _assign_impl(
            agent_profile, message, working_directory=working_directory, provider=provider
        )

else:

    @mcp.tool()
    async def assign(  # type: ignore[misc]
        agent_profile: str = Field(
            description='The agent profile for the worker agent (e.g., "developer", "analyst")'
        ),
        message: str = Field(
            min_length=1,
            description="The task message to send. Include callback instructions for the worker to send results back."
        ),
        provider: Optional[str] = Field(
            default=None,
            description="Optional provider override for the worker terminal",
        ),
    ) -> Dict[str, Any]:
        """Assigns a task to another agent without blocking.

        In the message to the worker agent include instruction to send results back via send_message tool.
        **IMPORTANT**: The terminal id of each agent is available in environment variable CAO_TERMINAL_ID.
        When assigning, first find out your own CAO_TERMINAL_ID value, then include the terminal_id value in the message to the worker agent to allow callback.
        Example message: "Analyze the logs. When done, send results back to terminal ee3f93b3 using send_message tool."

        Args:
            agent_profile: Agent profile for the worker terminal
            message: Task message (include callback instructions)
            provider: Optional provider override

        Returns:
            Dict with success status, worker terminal_id, and message
        """
        return _assign_impl(agent_profile, message, working_directory=None, provider=provider)


@mcp.tool()
async def send_message(
    receiver_id: str = Field(description="Target terminal ID to send message to"),
    message: str = Field(description="Message content to send"),
) -> Dict[str, Any]:
    """Send a message to another terminal's inbox.

    The message will be delivered when the destination terminal is IDLE.
    Messages are delivered in order (oldest first).

    Args:
        receiver_id: Terminal ID of the receiver
        message: Message content to send

    Returns:
        Dict with success status and message details
    """
    try:
        return _send_message_impl(receiver_id, message)
    except Exception as e:
        return {"success": False, "error": str(e)}


def main():
    """Main entry point for the MCP server."""
    mcp.run(show_banner=True, log_level="INFO")


if __name__ == "__main__":
    main()

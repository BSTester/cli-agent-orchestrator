"""Simplified tmux client as module singleton."""

import logging
import os
import subprocess
import time
import uuid
from typing import Dict, List, Optional

import libtmux

from cli_agent_orchestrator.constants import TMUX_HISTORY_LINES

logger = logging.getLogger(__name__)


class TmuxClient:
    """Simplified tmux client for basic operations."""

    def __init__(self) -> None:
        self.server = libtmux.Server()

    # Directories that should never be used as working directories.
    # Prevents user-supplied paths from pointing at sensitive system locations.
    _BLOCKED_DIRECTORIES = frozenset(
        {
            "/",
            "/bin",
            "/sbin",
            "/usr/bin",
            "/usr/sbin",
            "/etc",
            "/var",
            "/tmp",
            "/dev",
            "/proc",
            "/sys",
            "/root",
            "/boot",
            "/lib",
            "/lib64",
        }
    )

    _ALLOWED_WORKING_DIRECTORIES_ENV = "CAO_ALLOWED_WORKING_DIRECTORIES"

    @staticmethod
    def _default_workspace_directory(home_dir: str) -> str:
        return os.path.realpath(os.path.abspath(os.path.join(home_dir, "workspace")))

    @staticmethod
    def _is_within_directory(path: str, root: str) -> bool:
        """Return whether path is exactly root or a child of root."""
        return path == root or path.startswith(root + os.sep)

    def _get_allowed_working_directory_roots(self, home_dir: str) -> List[str]:
        """Build allowed root directories from home + optional env overrides.

        Environment variable format:
            CAO_ALLOWED_WORKING_DIRECTORIES=/path/a:/path/b
        """
        allowed_roots: List[str] = [home_dir]
        configured = os.getenv(self._ALLOWED_WORKING_DIRECTORIES_ENV, "")

        for raw_path in configured.split(os.pathsep):
            candidate = raw_path.strip()
            if not candidate:
                continue

            if not os.path.isabs(candidate):
                logger.warning(
                    "Ignoring non-absolute configured working directory root in %s: %s",
                    self._ALLOWED_WORKING_DIRECTORIES_ENV,
                    candidate,
                )
                continue

            resolved = os.path.realpath(os.path.abspath(candidate))

            if resolved in self._BLOCKED_DIRECTORIES:
                logger.warning(
                    "Ignoring blocked configured working directory root in %s: %s",
                    self._ALLOWED_WORKING_DIRECTORIES_ENV,
                    resolved,
                )
                continue

            if not os.path.isdir(resolved):
                logger.warning(
                    "Ignoring non-existent configured working directory root in %s: %s",
                    self._ALLOWED_WORKING_DIRECTORIES_ENV,
                    resolved,
                )
                continue

            if resolved not in allowed_roots:
                allowed_roots.append(resolved)

        return allowed_roots

    def _resolve_and_validate_working_directory(self, working_directory: Optional[str]) -> str:
        """Resolve and validate working directory.

        Canonicalizes the path (resolves symlinks, normalizes ``..``) and
        rejects paths that point to sensitive system directories or escape
        the user's home directory.

        **Allowed (safe) directories:**

        - The user's home directory itself (``~/``)
        - Any subdirectory under the home directory (``~/projects/foo``)
        - Paths that resolve to the home tree after symlink resolution
          (e.g., ``/home/user`` -> ``/local/home/user`` on AWS)

        **Blocked (unsafe) directories:**

        - System directories: ``/``, ``/bin``, ``/sbin``, ``/usr/bin``,
          ``/usr/sbin``, ``/etc``, ``/var``, ``/tmp``, ``/dev``, ``/proc``,
          ``/sys``, ``/root``, ``/boot``, ``/lib``, ``/lib64``
        - Any path outside the user's home directory tree

        Args:
            working_directory: Optional directory path, defaults to current directory

        Returns:
            Canonicalized absolute path

        Raises:
            ValueError: If directory does not exist, is a blocked system path,
                or is outside the user's home directory
        """
        home_dir = os.path.realpath(os.path.expanduser("~"))
        workspace_dir = self._default_workspace_directory(home_dir)
        explicit_directory = working_directory is not None
        allowed_roots = self._get_allowed_working_directory_roots(home_dir)

        if working_directory is None:
            working_directory = os.getcwd()

        # Step 1: Canonicalize both paths via realpath to resolve symlinks
        # and .. sequences.  os.path.realpath is recognized by CodeQL as a
        # PathNormalization (transitions taint to NormalizedUnchecked).
        # Using realpath on both sides ensures the comparison is consistent
        # in environments where the home directory is a symlink (e.g.,
        # /home/user -> /local/home/user on AWS).
        safe_working_directory = os.path.realpath(os.path.abspath(working_directory))

        # Step 2: Path containment check against allowed roots.
        if not any(
            self._is_within_directory(safe_working_directory, root) for root in allowed_roots
        ):
            if not explicit_directory:
                logger.warning(
                    "Current working directory %s is outside allowed roots %s; falling back to workspace directory",
                    safe_working_directory,
                    allowed_roots,
                )
                if not os.path.isdir(workspace_dir):
                    try:
                        os.makedirs(workspace_dir, exist_ok=True)
                    except OSError as exc:
                        logger.warning("Failed to create workspace directory %s: %s", workspace_dir, exc)
                safe_working_directory = workspace_dir
            else:
                raise ValueError(
                    f"Working directory not allowed: {working_directory} "
                    f"(resolves to {safe_working_directory}, which is outside "
                    f"home directory {home_dir} and configured allowed directories {allowed_roots})"
                )

        # Step 3: Re-check precise boundary against allowed roots.
        if not any(self._is_within_directory(safe_working_directory, root) for root in allowed_roots):
            raise ValueError(
                f"Working directory not allowed: {working_directory} "
                f"(resolves to {safe_working_directory}, which is outside "
                f"home directory {home_dir} and configured allowed directories {allowed_roots})"
            )

        # Step 4: Block sensitive system directories
        if safe_working_directory in self._BLOCKED_DIRECTORIES:
            raise ValueError(
                f"Working directory not allowed: {working_directory} "
                f"(resolves to blocked path {safe_working_directory})"
            )

        # Step 5: Resolve symlinks and re-validate containment.
        # This prevents symlink-based escapes from allowed roots.
        real_path = os.path.realpath(safe_working_directory)
        if not any(self._is_within_directory(real_path, root) for root in allowed_roots):
            raise ValueError(
                f"Working directory not allowed: {working_directory} "
                f"(symlink resolves to {real_path}, which is outside home directory "
                f"{home_dir} and configured allowed directories {allowed_roots})"
            )

        if not os.path.isdir(real_path):
            raise ValueError(f"Working directory does not exist: {working_directory}")

        return real_path

    def create_session(
        self,
        session_name: str,
        window_name: str,
        terminal_id: str,
        working_directory: Optional[str] = None,
    ) -> str:
        """Create detached tmux session with initial window and return window name."""
        try:
            working_directory = self._resolve_and_validate_working_directory(working_directory)

            environment = os.environ.copy()
            environment["CAO_TERMINAL_ID"] = terminal_id

            session = self.server.new_session(
                session_name=session_name,
                window_name=window_name,
                start_directory=working_directory,
                detach=True,
                environment=environment,
            )
            logger.info(
                f"Created tmux session: {session_name} with window: {window_name} in directory: {working_directory}"
            )
            window_name_result = session.windows[0].name
            if window_name_result is None:
                raise ValueError(f"Window name is None for session {session_name}")
            return window_name_result
        except Exception as e:
            logger.error(f"Failed to create session {session_name}: {e}")
            raise

    def create_window(
        self,
        session_name: str,
        window_name: str,
        terminal_id: str,
        working_directory: Optional[str] = None,
    ) -> str:
        """Create window in session and return window name."""
        try:
            working_directory = self._resolve_and_validate_working_directory(working_directory)

            session = self.server.sessions.get(session_name=session_name)
            if not session:
                raise ValueError(f"Session '{session_name}' not found")

            window = session.new_window(
                window_name=window_name,
                start_directory=working_directory,
                environment={"CAO_TERMINAL_ID": terminal_id},
            )

            logger.info(
                f"Created window '{window.name}' in session '{session_name}' in directory: {working_directory}"
            )
            window_name_result = window.name
            if window_name_result is None:
                raise ValueError(f"Window name is None for session {session_name}")
            return window_name_result
        except Exception as e:
            logger.error(f"Failed to create window in session {session_name}: {e}")
            raise

    def send_keys(
        self, session_name: str, window_name: str, keys: str, enter_count: int = 1
    ) -> None:
        """Send keys to window using tmux paste-buffer for instant delivery.

        Uses load-buffer + paste-buffer instead of chunked send-keys to avoid
        slow character-by-character input and special character interpretation.
        The -p flag enables bracketed paste mode so multi-line content is treated
        as a single input rather than submitting on each newline.

        Args:
            session_name: Name of tmux session
            window_name: Name of window in session
            keys: Text to send
            enter_count: Number of Enter keys to send after pasting (default 1).
                Some TUIs enter multi-line mode after bracketed paste,
                requiring 2 Enters to submit.
        """
        target = f"{session_name}:{window_name}"
        buf_name = f"cao_{uuid.uuid4().hex[:8]}"
        safe_enter_count = max(1, int(enter_count))
        try:
            logger.info(f"send_keys: {target} - keys: {keys}")
            subprocess.run(
                ["tmux", "load-buffer", "-b", buf_name, "-"],
                input=keys.encode(),
                check=True,
            )
            subprocess.run(
                ["tmux", "paste-buffer", "-p", "-b", buf_name, "-t", target],
                check=True,
            )
            # Brief delay to let the TUI process the bracketed paste end sequence
            # before sending Enter. Without this, some TUIs (e.g., Claude Code 2.x)
            # swallow the Enter that immediately follows paste-buffer -p.
            time.sleep(0.3)
            for i in range(safe_enter_count):
                if i > 0:
                    # Delay between Enter presses for TUIs that need time to
                    # process the previous Enter (e.g., Ink adding a newline)
                    # before the next Enter triggers form submission.
                    time.sleep(0.5)
                subprocess.run(
                    ["tmux", "send-keys", "-t", target, "Enter"],
                    check=True,
                )
            logger.debug(f"Sent keys to {target}")
        except Exception as e:
            logger.error(f"Failed to send keys to {target}: {e}")
            raise
        finally:
            subprocess.run(
                ["tmux", "delete-buffer", "-b", buf_name],
                check=False,
            )

    def send_keys_via_paste(self, session_name: str, window_name: str, text: str) -> None:
        """Send text to window via tmux paste buffer with bracketed paste mode.

        Uses tmux set-buffer + paste-buffer -p to send text as a bracketed paste,
        which bypasses TUI hotkey handling. Essential for Ink-based CLIs and
        other TUI apps where individual keystrokes may trigger hotkeys.

        After pasting, sends C-m (Enter) to submit the input.

        Args:
            session_name: Name of tmux session
            window_name: Name of window in session
            text: Text to paste into the pane
        """
        try:
            logger.info(
                f"send_keys_via_paste: {session_name}:{window_name} - text length: {len(text)}"
            )

            session = self.server.sessions.get(session_name=session_name)
            if not session:
                raise ValueError(f"Session '{session_name}' not found")

            window = session.windows.get(window_name=window_name)
            if not window:
                raise ValueError(f"Window '{window_name}' not found in session '{session_name}'")

            pane = window.active_pane
            if pane:
                buf_name = "cao_paste"

                # Load text into tmux buffer
                self.server.cmd("set-buffer", "-b", buf_name, text)

                # Paste with bracketed paste mode (-p flag).
                # This wraps the text in \x1b[200~ ... \x1b[201~ escape sequences,
                # telling the TUI "this is pasted text" so it bypasses hotkey handling.
                pane.cmd("paste-buffer", "-p", "-b", buf_name)

                time.sleep(0.3)

                # Send Enter to submit the pasted text
                pane.send_keys("C-m", enter=False)

                # Clean up the paste buffer
                try:
                    self.server.cmd("delete-buffer", "-b", buf_name)
                except Exception:
                    pass

                logger.debug(f"Sent text via paste to {session_name}:{window_name}")
        except Exception as e:
            logger.error(f"Failed to send text via paste to {session_name}:{window_name}: {e}")
            raise

    def send_special_key(self, session_name: str, window_name: str, key: str) -> None:
        """Send a tmux special key sequence (e.g., C-d, C-c) to a window.

        Unlike send_keys(), this sends the key as a tmux key name (not literal text)
        and does not append a carriage return. Used for control signals like Ctrl+D (EOF).

        Args:
            session_name: Name of tmux session
            window_name: Name of window in session
            key: Tmux key name (e.g., "C-d", "C-c", "Escape")
        """
        try:
            logger.info(f"send_special_key: {session_name}:{window_name} - key: {key}")

            session = self.server.sessions.get(session_name=session_name)
            if not session:
                raise ValueError(f"Session '{session_name}' not found")

            window = session.windows.get(window_name=window_name)
            if not window:
                raise ValueError(f"Window '{window_name}' not found in session '{session_name}'")

            pane = window.active_pane
            if pane:
                pane.send_keys(key, enter=False)
                logger.debug(f"Sent special key to {session_name}:{window_name}")
        except Exception as e:
            logger.error(f"Failed to send special key to {session_name}:{window_name}: {e}")
            raise

    def send_raw_input(self, session_name: str, window_name: str, text: str) -> None:
        """Send raw text bytes to a tmux pane without implicit Enter.

        Uses `tmux send-keys -H` with batched hex arguments to preserve control
        sequences and avoid bracketed-paste semantics. This is suitable for
        web-terminal style interactions where input should be applied exactly as
        typed.

        Args:
            session_name: Name of tmux session
            window_name: Name of window in session
            text: Raw text payload to send
        """
        if not text:
            return

        target = f"{session_name}:{window_name}"
        try:
            logger.info(f"send_raw_input: {target} - text length: {len(text)}")
            hex_bytes = [f"{byte:02x}" for byte in text.encode("utf-8")]

            # Send in chunks so multi-byte control sequences (e.g. ESC+[A) stay
            # contiguous and are interpreted correctly by tmux/shell.
            chunk_size = 64
            for start in range(0, len(hex_bytes), chunk_size):
                chunk = hex_bytes[start : start + chunk_size]
                subprocess.run(
                    ["tmux", "send-keys", "-t", target, "-H", *chunk],
                    check=True,
                )
            logger.debug(f"Sent raw input to {target}")
        except Exception as e:
            logger.error(f"Failed to send raw input to {target}: {e}")
            raise

    def resize_window(
        self,
        session_name: str,
        window_name: str,
        cols: int,
        rows: int,
    ) -> None:
        """Resize tmux window dimensions.

        Args:
            session_name: Name of tmux session
            window_name: Name of window in session
            cols: Target terminal columns
            rows: Target terminal rows
        """
        safe_cols = max(20, min(int(cols), 500))
        safe_rows = max(5, min(int(rows), 200))
        target = f"{session_name}:{window_name}"

        try:
            logger.debug(
                "resize_window: %s -> cols=%s rows=%s",
                target,
                safe_cols,
                safe_rows,
            )
            subprocess.run(
                ["tmux", "resize-window", "-t", target, "-x", str(safe_cols), "-y", str(safe_rows)],
                check=True,
            )
        except Exception as e:
            logger.error(f"Failed to resize window {target}: {e}")
            raise

    def get_history(
        self, session_name: str, window_name: str, tail_lines: Optional[int] = None
    ) -> str:
        """Get window history.

        Args:
            session_name: Name of tmux session
            window_name: Name of window in session
            tail_lines: Number of lines to capture from end (default: TMUX_HISTORY_LINES)
        """
        try:
            session = self.server.sessions.get(session_name=session_name)
            if not session:
                raise ValueError(f"Session '{session_name}' not found")

            window = session.windows.get(window_name=window_name)
            if not window:
                raise ValueError(f"Window '{window_name}' not found in session '{session_name}'")

            pane = window.panes[0]
            lines = tail_lines if tail_lines is not None else TMUX_HISTORY_LINES
            result = pane.cmd("capture-pane", "-e", "-p", "-S", f"-{lines}")
            if result.stdout:
                return "\n".join(result.stdout)

            alt_result = pane.cmd("capture-pane", "-a", "-e", "-p", "-S", f"-{lines}")
            return "\n".join(alt_result.stdout) if alt_result.stdout else ""
        except Exception as e:
            logger.error(f"Failed to get history from {session_name}:{window_name}: {e}")
            raise

    def list_sessions(self) -> List[Dict[str, str]]:
        """List all tmux sessions."""
        try:
            sessions: List[Dict[str, str]] = []
            for session in self.server.sessions:
                # Check if session has attached clients
                is_attached = len(getattr(session, "attached_sessions", [])) > 0

                session_name = session.name if session.name is not None else ""
                sessions.append(
                    {
                        "id": session_name,
                        "name": session_name,
                        "status": "active" if is_attached else "detached",
                    }
                )

            return sessions
        except Exception as e:
            logger.error(f"Failed to list sessions: {e}")
            return []

    def get_session_windows(self, session_name: str) -> List[Dict[str, str]]:
        """Get all windows in a session."""
        try:
            session = self.server.sessions.get(session_name=session_name)
            if not session:
                return []

            windows: List[Dict[str, str]] = []
            for window in session.windows:
                window_name = window.name if window.name is not None else ""
                windows.append({"name": window_name, "index": str(window.index)})

            return windows
        except Exception as e:
            logger.error(f"Failed to get windows for session {session_name}: {e}")
            return []

    def kill_window(self, session_name: str, window_name: str) -> bool:
        """Kill a specific tmux window."""
        try:
            session = self.server.sessions.get(session_name=session_name)
            if not session:
                return False

            window = session.windows.get(window_name=window_name)
            if window:
                window.kill_window()
                logger.info(f"Killed window '{window_name}' in session '{session_name}'")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to kill window {window_name} in session {session_name}: {e}")
            return False

    def kill_session(self, session_name: str) -> bool:
        """Kill tmux session."""
        try:
            session = self.server.sessions.get(session_name=session_name)
            if session:
                session.kill()
                logger.info(f"Killed tmux session: {session_name}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to kill session {session_name}: {e}")
            return False

    def session_exists(self, session_name: str) -> bool:
        """Check if session exists."""
        try:
            session = self.server.sessions.get(session_name=session_name)
            return session is not None
        except Exception:
            return False

    def get_pane_working_directory(self, session_name: str, window_name: str) -> Optional[str]:
        """Get the current working directory of a pane."""
        try:
            session = self.server.sessions.get(session_name=session_name)
            if not session:
                return None

            window = session.windows.get(window_name=window_name)
            if not window:
                return None

            pane = window.active_pane
            if pane:
                # Get pane_current_path from tmux
                result = pane.cmd("display-message", "-p", "#{pane_current_path}")
                if result.stdout:
                    return result.stdout[0].strip()
            return None
        except Exception as e:
            logger.error(f"Failed to get working directory for {session_name}:{window_name}: {e}")
            return None

    def pipe_pane(self, session_name: str, window_name: str, file_path: str) -> None:
        """Start piping pane output to file.

        Args:
            session_name: Tmux session name
            window_name: Tmux window name
            file_path: Absolute path to log file
        """
        try:
            session = self.server.sessions.get(session_name=session_name)
            if not session:
                raise ValueError(f"Session '{session_name}' not found")

            window = session.windows.get(window_name=window_name)
            if not window:
                raise ValueError(f"Window '{window_name}' not found in session '{session_name}'")

            pane = window.active_pane
            if pane:
                pane.cmd("pipe-pane", "-o", f"cat >> {file_path}")
                logger.info(f"Started pipe-pane for {session_name}:{window_name} to {file_path}")
        except Exception as e:
            logger.error(f"Failed to start pipe-pane for {session_name}:{window_name}: {e}")
            raise

    def stop_pipe_pane(self, session_name: str, window_name: str) -> None:
        """Stop piping pane output.

        Args:
            session_name: Tmux session name
            window_name: Tmux window name
        """
        try:
            session = self.server.sessions.get(session_name=session_name)
            if not session:
                raise ValueError(f"Session '{session_name}' not found")

            window = session.windows.get(window_name=window_name)
            if not window:
                raise ValueError(f"Window '{window_name}' not found in session '{session_name}'")

            pane = window.active_pane
            if pane:
                pane.cmd("pipe-pane")
                logger.info(f"Stopped pipe-pane for {session_name}:{window_name}")
        except Exception as e:
            logger.error(f"Failed to stop pipe-pane for {session_name}:{window_name}: {e}")
            raise


# Module-level singleton
tmux_client = TmuxClient()

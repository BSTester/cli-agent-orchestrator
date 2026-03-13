import subprocess
from pathlib import Path


def _script_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "scripts" / "start_services.sh"


def _make_stub_command(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _prepare_stub_tools(bin_dir: Path) -> None:
    _make_stub_command(bin_dir / "curl", "#!/usr/bin/env bash\nexit 0\n")
    # Use a correct env stub that handles NAME=VALUE prefix args before the command
    _make_stub_command(
        bin_dir / "env",
        """#!/usr/bin/env bash
while [[ $# -gt 0 && "$1" == *=* ]]; do
  export "$1"
  shift
done
exec "$@"
""",
    )
    _make_stub_command(bin_dir / "cao-server", "#!/usr/bin/env bash\nsleep 5\n")
    _make_stub_command(
        bin_dir / "cao-control-panel", "#!/usr/bin/env bash\nsleep 5\n"
    )
    _make_stub_command(
        bin_dir / "openclaw",
        """#!/usr/bin/env bash
set -euo pipefail
log_file="${OPENCLAW_GATEWAY_CALL_LOG:-}"
state_file="${OPENCLAW_GATEWAY_STATE_FILE:-}"
if [[ -z "$state_file" && -n "$log_file" ]]; then
    state_file="${log_file}.state"
fi
if [[ -n "$log_file" ]]; then
    echo "$*" >> "$log_file"
fi

if [[ "${1-}" == "gateway" && "${2-}" == "status" ]]; then
    if [[ "${OPENCLAW_GATEWAY_STATUS:-stopped}" == "running" || ( -n "$state_file" && -f "$state_file" ) ]]; then
        cat <<'EOF'
Service: systemd (enabled)
Runtime: running (pid 123, state active, sub running, last exit 0, reason 0)
RPC probe: ok
EOF
    else
        cat <<'EOF'
Service: systemd (enabled)
Runtime: stopped (state inactive)
RPC probe: unavailable
EOF
    fi
    exit 0
fi

if [[ "${1-}" == "gateway" && ( "${2-}" == "start" || "${2-}" == "restart" ) ]]; then
    if [[ -n "$state_file" ]]; then
        touch "$state_file"
    fi
    exit 0
fi

if [[ "${1-}" == "gateway" && $# -eq 1 ]]; then
    if [[ -n "$state_file" ]]; then
        touch "$state_file"
    fi
    sleep 5
    exit 0
fi

exit 0
""",
    )


def _kill_pid_file(pid_file: Path) -> None:
    if pid_file.exists():
        pid = pid_file.read_text(encoding="utf-8").strip()
        if pid:
            subprocess.run(["kill", "-9", pid], check=False, capture_output=True)


def test_start_services_creates_pid_files_relative_to_script(tmp_path: Path) -> None:
    script_path = _script_path()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _prepare_stub_tools(bin_dir)
    gateway_log = tmp_path / "openclaw-gateway.log"

    result = subprocess.run(
        ["bash", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "OPENCLAW_GATEWAY_CALL_LOG": str(gateway_log),
        },
    )

    repo_root = script_path.parent.parent
    server_pid_file = repo_root / ".runtime" / "pids" / "cao-server.pid"
    panel_pid_file = repo_root / ".runtime" / "pids" / "cao-control-panel.pid"

    try:
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert server_pid_file.exists(), "cao-server PID file was not created"
        assert panel_pid_file.exists(), "cao-control-panel PID file was not created"
        assert "[INFO] 全部服务已启动" in result.stdout
        assert gateway_log.read_text(encoding="utf-8").splitlines() == [
            "gateway status",
            "gateway start",
            "gateway status",
        ]
    finally:
        _kill_pid_file(server_pid_file)
        _kill_pid_file(panel_pid_file)
        server_pid_file.unlink(missing_ok=True)
        panel_pid_file.unlink(missing_ok=True)


def test_start_services_skips_already_running_service(tmp_path: Path) -> None:
    script_path = _script_path()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _prepare_stub_tools(bin_dir)
    gateway_log = tmp_path / "openclaw-gateway.log"

    result = subprocess.run(
        ["bash", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "OPENCLAW_GATEWAY_CALL_LOG": str(gateway_log),
        },
    )

    repo_root = script_path.parent.parent
    server_pid_file = repo_root / ".runtime" / "pids" / "cao-server.pid"
    panel_pid_file = repo_root / ".runtime" / "pids" / "cao-control-panel.pid"

    try:
        assert result.returncode == 0

        # Run again: should detect services are already running
        result2 = subprocess.run(
            ["bash", str(script_path)],
            capture_output=True,
            text=True,
            check=False,
            env={
                "PATH": f"{bin_dir}:/usr/bin:/bin",
                "HOME": str(tmp_path),
                "OPENCLAW_GATEWAY_CALL_LOG": str(gateway_log),
                "OPENCLAW_GATEWAY_STATUS": "running",
            },
        )

        assert result2.returncode == 0
        assert "已在运行" in result2.stdout
        assert gateway_log.read_text(encoding="utf-8").splitlines() == [
            "gateway status",
            "gateway start",
            "gateway status",
            "gateway status",
            "gateway restart",
            "gateway status",
        ]
    finally:
        _kill_pid_file(server_pid_file)
        _kill_pid_file(panel_pid_file)
        server_pid_file.unlink(missing_ok=True)
        panel_pid_file.unlink(missing_ok=True)


def test_start_services_fails_when_required_command_missing(tmp_path: Path) -> None:
    script_path = _script_path()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Do NOT add cao-server or cao-control-panel stubs
    _make_stub_command(bin_dir / "curl", "#!/usr/bin/env bash\nexit 0\n")

    result = subprocess.run(
        ["bash", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(tmp_path),
        },
    )

    assert result.returncode != 0
    assert "缺少命令" in result.stderr


def test_start_services_can_skip_openclaw_gateway(tmp_path: Path) -> None:
    script_path = _script_path()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _prepare_stub_tools(bin_dir)
    gateway_log = tmp_path / "openclaw-gateway.log"

    result = subprocess.run(
        ["bash", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "OPENCLAW_GATEWAY_ENABLE": "0",
            "OPENCLAW_GATEWAY_CALL_LOG": str(gateway_log),
        },
    )

    repo_root = script_path.parent.parent
    server_pid_file = repo_root / ".runtime" / "pids" / "cao-server.pid"
    panel_pid_file = repo_root / ".runtime" / "pids" / "cao-control-panel.pid"

    try:
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "已跳过 OpenClaw gateway 启动" in result.stdout
        assert not gateway_log.exists()
    finally:
        _kill_pid_file(server_pid_file)
        _kill_pid_file(panel_pid_file)
        server_pid_file.unlink(missing_ok=True)
        panel_pid_file.unlink(missing_ok=True)


def test_start_services_falls_back_to_managed_gateway_process_when_service_unavailable(
    tmp_path: Path,
) -> None:
    script_path = _script_path()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _prepare_stub_tools(bin_dir)
    gateway_log = tmp_path / "openclaw-gateway.log"
    _make_stub_command(
        bin_dir / "openclaw",
        f"""#!/usr/bin/env bash
set -euo pipefail
log_file="{gateway_log}"
echo "$*" >> "$log_file"

if [[ "${{1-}}" == "gateway" && "${{2-}}" == "status" ]]; then
    if [[ -f "{tmp_path / 'gateway-ready'}" ]]; then
        cat <<'EOF'
Service: systemd (missing)
Runtime: running (pid 234, state active, sub running, last exit 0, reason 0)
EOF
    else
        cat <<'EOF'
systemd user services are unavailable; install/enable systemd or run the gateway under your supervisor.
EOF
    fi
    exit 0
fi

if [[ "${{1-}}" == "gateway" && "${{2-}}" == "install" ]]; then
    exit 1
fi

if [[ "${{1-}}" == "gateway" && $# -eq 1 ]]; then
    touch "{tmp_path / 'gateway-ready'}"
    sleep 5
    exit 0
fi

exit 0
""",
    )

    result = subprocess.run(
        ["bash", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "HOME": str(tmp_path),
        },
    )

    repo_root = script_path.parent.parent
    gateway_pid_file = repo_root / ".runtime" / "pids" / "openclaw-gateway.pid"
    server_pid_file = repo_root / ".runtime" / "pids" / "cao-server.pid"
    panel_pid_file = repo_root / ".runtime" / "pids" / "cao-control-panel.pid"

    try:
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert gateway_pid_file.exists(), "openclaw-gateway PID file was not created"
        assert "脚本托管模式" in result.stdout
        gateway_calls = gateway_log.read_text(encoding="utf-8").splitlines()
        assert gateway_calls[0] == "gateway status"
        assert "gateway install --force" in gateway_calls
        assert "gateway" in gateway_calls
        assert gateway_calls[-1] == "gateway status"
    finally:
        _kill_pid_file(gateway_pid_file)
        _kill_pid_file(server_pid_file)
        _kill_pid_file(panel_pid_file)
        gateway_pid_file.unlink(missing_ok=True)
        server_pid_file.unlink(missing_ok=True)
        panel_pid_file.unlink(missing_ok=True)

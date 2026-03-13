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
if [[ -n "$log_file" ]]; then
    echo "$*" >> "$log_file"
fi

if [[ "${1-}" == "gateway" && "${2-}" == "status" ]]; then
    if [[ "${OPENCLAW_GATEWAY_STATUS:-stopped}" == "running" ]]; then
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
            "gateway restart",
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

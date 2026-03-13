import shutil
import subprocess
from pathlib import Path


def _make_stub_command(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_docker_entrypoint_repairs_missing_provider_before_start(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()

    shutil.copy2(repo_root / "scripts" / "docker_entrypoint.sh", scripts_dir / "docker_entrypoint.sh")

    (scripts_dir / "install_services.sh").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "install_missing_agent_clis() {\n"
        "  echo runtime-repair >> \"$ENTRYPOINT_LOG\"\n"
        "}\n",
        encoding="utf-8",
    )
    (scripts_dir / "install_services.sh").chmod(0o755)

    (scripts_dir / "start_services.sh").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "echo start-services >> \"$ENTRYPOINT_LOG\"\n",
        encoding="utf-8",
    )
    (scripts_dir / "start_services.sh").chmod(0o755)

    (scripts_dir / "install_and_start_services.sh").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "echo install-and-start >> \"$ENTRYPOINT_LOG\"\n",
        encoding="utf-8",
    )
    (scripts_dir / "install_and_start_services.sh").chmod(0o755)

    tail_log = tmp_path / "tail.log"
    _make_stub_command(
        tmp_path / "tail",
        f"#!/usr/bin/env bash\nset -euo pipefail\necho \"$*\" >> \"{tail_log}\"\nexit 0\n",
    )

    entrypoint_log = tmp_path / "entrypoint.log"
    result = subprocess.run(
        ["bash", str(scripts_dir / "docker_entrypoint.sh")],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "ENTRYPOINT_LOG": str(entrypoint_log),
            "CAO_RUNTIME_DIR": str(tmp_path / ".runtime"),
        },
    )

    assert result.returncode == 0, result.stderr
    log_content = entrypoint_log.read_text(encoding="utf-8").splitlines()
    assert log_content == ["runtime-repair", "start-services"]
    assert "启动前校验 7 个 provider CLI，缺失项将按需补装。" in result.stdout


def test_docker_entrypoint_can_skip_runtime_provider_verification(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()

    shutil.copy2(repo_root / "scripts" / "docker_entrypoint.sh", scripts_dir / "docker_entrypoint.sh")

    (scripts_dir / "install_services.sh").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "install_missing_agent_clis() {\n"
        "  echo should-not-run >> \"$ENTRYPOINT_LOG\"\n"
        "}\n",
        encoding="utf-8",
    )
    (scripts_dir / "install_services.sh").chmod(0o755)

    (scripts_dir / "start_services.sh").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "echo start-services >> \"$ENTRYPOINT_LOG\"\n",
        encoding="utf-8",
    )
    (scripts_dir / "start_services.sh").chmod(0o755)

    (scripts_dir / "install_and_start_services.sh").write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "echo install-and-start >> \"$ENTRYPOINT_LOG\"\n",
        encoding="utf-8",
    )
    (scripts_dir / "install_and_start_services.sh").chmod(0o755)

    _make_stub_command(
        tmp_path / "tail",
        "#!/usr/bin/env bash\nset -euo pipefail\nexit 0\n",
    )

    entrypoint_log = tmp_path / "entrypoint.log"
    result = subprocess.run(
        ["bash", str(scripts_dir / "docker_entrypoint.sh")],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": f"{tmp_path}:/usr/bin:/bin",
            "HOME": str(tmp_path),
            "ENTRYPOINT_LOG": str(entrypoint_log),
            "CAO_RUNTIME_DIR": str(tmp_path / ".runtime"),
            "CAO_VERIFY_AGENT_CLIS_ON_START": "0",
        },
    )

    assert result.returncode == 0, result.stderr
    assert entrypoint_log.read_text(encoding="utf-8").splitlines() == ["start-services"]
    assert "已跳过 provider CLI 启动校验" in result.stdout
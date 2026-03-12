import subprocess
from pathlib import Path


def _script_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "scripts" / "docker_init_bind_mounts.sh"


def _make_stub_command(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _prepare_stub_docker(bin_dir: Path, image_root: Path, log_file: Path) -> None:
    _make_stub_command(
        bin_dir / "docker",
        f"""#!/usr/bin/env bash
set -euo pipefail
log_file={str(log_file)!r}
image_root={str(image_root)!r}
cmd="${{1-}}"
shift || true

case "$cmd" in
  image)
    if [[ "${{1-}}" == "inspect" ]]; then
      exit 0
    fi
    ;;
  create)
    echo "create $*" >> "$log_file"
    echo "stub-container"
    exit 0
    ;;
  cp)
    src="${{1-}}"
    dest="${{2-}}"
    echo "cp $src $dest" >> "$log_file"
    container_path="${{src#*:}}"
    trimmed_path="${{container_path%/.}}"
    source_path="$image_root$trimmed_path"
    mkdir -p "$dest"
    cp -a "$source_path/." "$dest"
    exit 0
    ;;
  rm)
    echo "rm $*" >> "$log_file"
    exit 0
    ;;
esac

echo "unexpected docker invocation: $cmd $*" >&2
exit 1
""",
    )


def test_initialize_bind_mounts_copies_defaults_into_empty_host_dirs(tmp_path: Path) -> None:
    script_path = _script_path()
    image_root = tmp_path / "image-root"
    docker_root = tmp_path / "docker-root"
    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "docker.log"
    bin_dir.mkdir()

    (image_root / "home" / "cao" / ".claude").mkdir(parents=True)
    (image_root / "home" / "cao" / ".claude" / "settings.json").write_text('{"theme":"dark"}', encoding="utf-8")
    (image_root / "home" / "cao" / ".aws" / "amazonq" / "cli-agents").mkdir(parents=True)
    (image_root / "home" / "cao" / ".aws" / "amazonq" / "cli-agents" / "worker.json").write_text(
        "q-agent",
        encoding="utf-8",
    )
    (image_root / "home" / "cao" / ".copilot" / "agents").mkdir(parents=True)
    (image_root / "home" / "cao" / ".copilot" / "agents" / "helper.md").write_text("agent", encoding="utf-8")

    _prepare_stub_docker(bin_dir, image_root, log_file)

    result = subprocess.run(
        ["bash", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "DOCKER_INIT_ROOT": str(docker_root),
            "DOCKER_INIT_IMAGE": "cao-dashboard",
        },
    )

    assert result.returncode == 0, result.stderr
    assert (docker_root / "claude" / "settings.json").read_text(encoding="utf-8") == '{"theme":"dark"}'
    assert (docker_root / "aws" / "amazonq" / "cli-agents" / "worker.json").read_text(encoding="utf-8") == "q-agent"
    assert (docker_root / "copilot" / "agents" / "helper.md").read_text(encoding="utf-8") == "agent"
    log_content = log_file.read_text(encoding="utf-8")
    assert "create cao-dashboard true" in log_content
    assert "cp stub-container:/home/cao/.claude/." in log_content
    assert "rm -f stub-container" in log_content


def test_initialize_bind_mounts_preserves_existing_host_content(tmp_path: Path) -> None:
    script_path = _script_path()
    image_root = tmp_path / "image-root"
    docker_root = tmp_path / "docker-root"
    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "docker.log"
    bin_dir.mkdir()

    (image_root / "home" / "cao" / ".claude").mkdir(parents=True)
    (image_root / "home" / "cao" / ".claude" / "settings.json").write_text('{"theme":"dark"}', encoding="utf-8")
    (docker_root / "claude").mkdir(parents=True)
    (docker_root / "claude" / "settings.json").write_text('{"theme":"light"}', encoding="utf-8")

    _prepare_stub_docker(bin_dir, image_root, log_file)

    result = subprocess.run(
        ["bash", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "DOCKER_INIT_ROOT": str(docker_root),
            "DOCKER_INIT_IMAGE": "cao-dashboard",
        },
    )

    assert result.returncode == 0, result.stderr
    assert (docker_root / "claude" / "settings.json").read_text(encoding="utf-8") == '{"theme":"light"}'
    assert "跳过非空目录" in result.stdout

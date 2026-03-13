import subprocess
from pathlib import Path


def _script_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "scripts" / "docker_init_bind_mounts.sh"


def _make_stub_command(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _prepare_stub_docker(bin_dir: Path, image_root: Path, host_root: Path, log_file: Path) -> None:
    _make_stub_command(
        bin_dir / "docker",
        f"""#!/usr/bin/env bash
set -euo pipefail
log_file={str(log_file)!r}
image_root={str(image_root)!r}
host_root={str(host_root)!r}
compose_container_id="compose-stub-container"
cmd="${{1-}}"
shift || true

case "$cmd" in
    compose)
        while [[ "${{1-}}" == -* ]]; do
            if [[ "$1" == "-p" ]]; then
                shift 2
                continue
            fi
            shift || true
        done
        subcmd="${{1-}}"
        shift || true
        case "$subcmd" in
            version)
                exit 0
                ;;
            create)
                echo "compose create $*" >> "$log_file"
                exit 0
                ;;
            ps)
                echo "$compose_container_id"
                exit 0
                ;;
            rm)
                echo "compose rm $*" >> "$log_file"
                exit 0
                ;;
        esac
        ;;
  image)
    if [[ "${{1-}}" == "inspect" ]]; then
      exit 0
    fi
    ;;
    inspect)
        while [[ "${{1-}}" == -* ]]; do
            if [[ "$1" == "--format" ]]; then
                shift 2
                continue
            fi
            shift || true
        done
        target="${{1-}}"
        if [[ "$target" == "$compose_container_id" ]]; then
            cat <<EOF
bind\t$host_root/aws\t/home/cao/.aws
bind\t$host_root/claude\t/home/cao/.claude
bind\t$host_root/copilot\t/home/cao/.copilot
volume	ignored-volume	/var/lib/example
EOF
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


def test_initialize_bind_mounts_copies_discovered_bind_mounts_into_empty_host_dirs(tmp_path: Path) -> None:
    script_path = _script_path()
    image_root = tmp_path / "image-root"
    host_root = tmp_path / "host-config"
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

    _prepare_stub_docker(bin_dir, image_root, host_root, log_file)

    result = subprocess.run(
        ["bash", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "DOCKER_INIT_IMAGE": "cao-dashboard",
        },
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert (host_root / "claude" / "settings.json").read_text(encoding="utf-8") == '{"theme":"dark"}'
    assert (host_root / "aws" / "amazonq" / "cli-agents" / "worker.json").read_text(encoding="utf-8") == "q-agent"
    assert (host_root / "copilot" / "agents" / "helper.md").read_text(encoding="utf-8") == "agent"
    log_content = log_file.read_text(encoding="utf-8")
    assert "compose create cao" in log_content
    assert "create cao-dashboard true" in log_content
    assert "cp stub-container:/home/cao/.claude/." in log_content
    assert "compose rm -fsv cao" in log_content
    assert "rm -f stub-container" in log_content


def test_initialize_bind_mounts_preserves_existing_host_content(tmp_path: Path) -> None:
    script_path = _script_path()
    image_root = tmp_path / "image-root"
    host_root = tmp_path / "host-config"
    bin_dir = tmp_path / "bin"
    log_file = tmp_path / "docker.log"
    bin_dir.mkdir()

    (image_root / "home" / "cao" / ".claude").mkdir(parents=True)
    (image_root / "home" / "cao" / ".claude" / "settings.json").write_text('{"theme":"dark"}', encoding="utf-8")
    (host_root / "claude").mkdir(parents=True, exist_ok=True)
    (host_root / "claude" / "settings.json").write_text('{"theme":"light"}', encoding="utf-8")

    _prepare_stub_docker(bin_dir, image_root, host_root, log_file)

    result = subprocess.run(
        ["bash", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "DOCKER_INIT_IMAGE": "cao-dashboard",
        },
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert (host_root / "claude" / "settings.json").read_text(encoding="utf-8") == '{"theme":"light"}'
    assert "跳过非空目录" in result.stdout

import subprocess
from pathlib import Path


def _script_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "scripts" / "docker_entrypoint.sh"


def _function_header() -> str:
    script = _script_path().read_text(encoding="utf-8")
    marker = "\nseed_persistent_provider_paths\n"
    return script.split(marker, 1)[0]


def _run_seed(template_dir: Path, home_dir: Path) -> subprocess.CompletedProcess[str]:
    shell_script = f"""{_function_header()}
HOME_TEMPLATE_DIR="{template_dir}"
HOME="{home_dir}"
seed_persistent_provider_paths
"""
    return subprocess.run(
        ["bash"],
        input=shell_script,
        capture_output=True,
        text=True,
        check=False,
    )


def test_seed_persistent_provider_paths_copies_only_requested_defaults(tmp_path: Path) -> None:
    template_dir = tmp_path / "template"
    home_dir = tmp_path / "home"

    (template_dir / ".claude").mkdir(parents=True)
    (template_dir / ".claude" / "settings.json").write_text('{"theme":"dark"}', encoding="utf-8")
    (template_dir / ".claude" / "history.log").write_text("too-large", encoding="utf-8")
    (template_dir / ".openclaw").mkdir(parents=True)
    (template_dir / ".openclaw" / "openclaw.json").write_text('{"provider":"zai"}', encoding="utf-8")
    (template_dir / ".openclaw" / "cache.db").write_text("skip-me", encoding="utf-8")
    (template_dir / ".aws" / "cli-agent-orchestrator" / "agent-context").mkdir(parents=True)
    (template_dir / ".aws" / "cli-agent-orchestrator" / "agent-context" / "default.md").write_text(
        "seeded",
        encoding="utf-8",
    )
    (template_dir / ".copilot" / "agents").mkdir(parents=True)
    (template_dir / ".copilot" / "agents" / "helper.md").write_text("agent", encoding="utf-8")
    (template_dir / ".copilot" / "oauth.json").write_text("skip-me", encoding="utf-8")

    (home_dir / ".claude").mkdir(parents=True)
    (home_dir / ".openclaw").mkdir(parents=True)
    (home_dir / ".aws" / "cli-agent-orchestrator").mkdir(parents=True)
    (home_dir / ".copilot").mkdir(parents=True)

    result = _run_seed(template_dir, home_dir)

    assert result.returncode == 0, result.stderr
    assert (home_dir / ".claude" / "settings.json").read_text(encoding="utf-8") == '{"theme":"dark"}'
    assert not (home_dir / ".claude" / "history.log").exists()
    assert (home_dir / ".openclaw" / "openclaw.json").read_text(encoding="utf-8") == '{"provider":"zai"}'
    assert not (home_dir / ".openclaw" / "cache.db").exists()
    assert (
        home_dir / ".aws" / "cli-agent-orchestrator" / "agent-context" / "default.md"
    ).read_text(encoding="utf-8") == "seeded"
    assert (home_dir / ".copilot" / "agents" / "helper.md").read_text(encoding="utf-8") == "agent"
    assert not (home_dir / ".copilot" / "oauth.json").exists()
    assert "[INFO] 初始化 provider 配置文件：" in result.stdout
    assert "[INFO] 初始化 provider 配置目录：" in result.stdout


def test_seed_persistent_provider_paths_preserves_existing_host_content(tmp_path: Path) -> None:
    template_dir = tmp_path / "template"
    home_dir = tmp_path / "home"

    (template_dir / ".claude").mkdir(parents=True)
    (template_dir / ".claude" / "settings.json").write_text('{"theme":"dark"}', encoding="utf-8")
    (home_dir / ".claude").mkdir(parents=True)
    (home_dir / ".claude" / "settings.json").write_text('{"theme":"light"}', encoding="utf-8")

    result = _run_seed(template_dir, home_dir)

    assert result.returncode == 0, result.stderr
    assert (home_dir / ".claude" / "settings.json").read_text(encoding="utf-8") == '{"theme":"light"}'
    assert "[INFO] 初始化 provider 配置文件：" not in result.stdout

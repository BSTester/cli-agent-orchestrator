import subprocess
import shutil
from pathlib import Path

import pytest


def _script_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "scripts" / "install_services.sh"


def _make_stub_command(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _prepare_stub_tools(bin_dir: Path, tmp_path: Path) -> None:
    _make_stub_command(
        bin_dir / "npm",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1-}" == "config" && "${2-}" == "get" && "${3-}" == "prefix" ]]; then
  echo "$HOME/.npm-global"
  exit 0
fi
exit 0
""",
    )
    _make_stub_command(bin_dir / "npx", "#!/usr/bin/env bash\nexit 0\n")
    _make_stub_command(bin_dir / "uv", "#!/usr/bin/env bash\nexit 0\n")
    for cmd in [
        "curl",
        "git",
        "python3",
        "node",
        "tmux",
        "codex",
        "claude",
        "kiro-cli",
        "qodercli",
        "codebuddy",
        "copilot",
        "cao",
        "cao-server",
        "cao-control-panel",
    ]:
        _make_stub_command(bin_dir / cmd, "#!/usr/bin/env bash\nexit 0\n")


def test_install_services_header_supports_stdin_execution() -> None:
    script_path = _script_path()
    header_lines = []
    for line in script_path.read_text(encoding="utf-8").splitlines(keepends=True):
        if line.strip() == "# INSTALLER_BOOTSTRAP_END":
            break
        header_lines.append(line)
    header = "".join(header_lines)

    result = subprocess.run(
        ["bash"],
        input=header,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""


def test_skills_discovery_non_interactive_terminal_prints_manual_command(tmp_path: Path) -> None:
    script_path = _script_path()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _prepare_stub_tools(bin_dir, tmp_path)
    npx_log = tmp_path / "npx.log"
    _make_stub_command(
        bin_dir / "npx",
        f"""#!/usr/bin/env bash
set -euo pipefail
echo "$*" > "{npx_log}"
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

    assert result.returncode == 0
    assert not npx_log.exists()
    assert "当前终端不支持交互式安装 skills-discovery。" in result.stderr
    assert (
        'skills-discovery 自动安装失败，请手动执行：npx -y "skills-installer" install '
        '"@Kamalnrf/claude-plugins/skills-discovery"'
    ) in result.stderr


def test_skills_discovery_install_unsets_legacy_npm_init_module_env(tmp_path: Path) -> None:
    if shutil.which("script") is None:
        pytest.skip("script command is required for pseudo-tty validation")

    script_path = _script_path()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _prepare_stub_tools(bin_dir, tmp_path)

    npx_log = tmp_path / "npx.log"
    _make_stub_command(
        bin_dir / "npx",
        f"""#!/usr/bin/env bash
set -euo pipefail
echo "npm_config_init_module=${{npm_config_init_module-unset}}" > "{npx_log}"
echo "NPM_CONFIG_INIT_MODULE=${{NPM_CONFIG_INIT_MODULE-unset}}" >> "{npx_log}"
exit 0
""",
    )

    script_cmd = ["script", "-qec", f"bash {script_path}", "/dev/null"]
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "npm_config_init_module": "/tmp/legacy-init.js",
        "NPM_CONFIG_INIT_MODULE": "/tmp/legacy-init.js",
    }
    result = subprocess.run(
        script_cmd,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )

    assert result.returncode == 0
    assert npx_log.exists()
    npx_log_content = npx_log.read_text(encoding="utf-8")
    assert "npm_config_init_module=unset" in npx_log_content
    assert "NPM_CONFIG_INIT_MODULE=unset" in npx_log_content


def test_skills_discovery_install_failure_prints_manual_command(tmp_path: Path) -> None:
    script_path = _script_path()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _prepare_stub_tools(bin_dir, tmp_path)
    _make_stub_command(
        bin_dir / "npx",
        """#!/usr/bin/env bash
set -euo pipefail
exit 1
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

    assert result.returncode == 0
    assert (
        'skills-discovery 自动安装失败，请手动执行：npx -y "skills-installer" install '
        '"@Kamalnrf/claude-plugins/skills-discovery"'
    ) in result.stderr


def test_agent_cli_install_failure_prints_manual_command(tmp_path: Path) -> None:
    script_path = _script_path()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _prepare_stub_tools(bin_dir, tmp_path)
    (bin_dir / "copilot").unlink()
    _make_stub_command(
        bin_dir / "npm",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1-}" == "config" && "${2-}" == "get" && "${3-}" == "prefix" ]]; then
  echo "$HOME/.npm-global"
  exit 0
fi
if [[ "${1-}" == "install" && "${2-}" == "-g" && "${3-}" == "@github/copilot" ]]; then
  exit 1
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

    assert result.returncode == 0
    assert "copilot 自动安装失败，请手动执行：npm install -g @github/copilot" in result.stderr


def test_skips_codex_claude_and_codebuddy_auto_install(tmp_path: Path) -> None:
    script_path = _script_path()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _prepare_stub_tools(bin_dir, tmp_path)

    (bin_dir / "codex").unlink()
    (bin_dir / "claude").unlink()
    (bin_dir / "codebuddy").unlink()

    npm_log = tmp_path / "npm.log"
    curl_log = tmp_path / "curl.log"
    _make_stub_command(
        bin_dir / "npm",
        f"""#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "{npm_log}"
if [[ "${{1-}}" == "config" && "${{2-}}" == "get" && "${{3-}}" == "prefix" ]]; then
  echo "$HOME/.npm-global"
fi
exit 0
""",
    )
    _make_stub_command(
        bin_dir / "curl",
        f"""#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "{curl_log}"
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

    assert result.returncode == 0
    npm_log_content = npm_log.read_text(encoding="utf-8")
    assert "install -g @openai/codex --force --no-os-check" not in npm_log_content
    assert "install -g @tencent-ai/codebuddy-code" not in npm_log_content
    assert "install -g @github/copilot" not in npm_log_content
    assert not curl_log.exists()
    assert "codex 自动安装失败" not in result.stderr
    assert "claude 自动安装失败" not in result.stderr
    assert "codebuddy 自动安装失败" not in result.stderr


def test_installs_default_agent_profiles(tmp_path: Path) -> None:
    script_path = _script_path()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _prepare_stub_tools(bin_dir, tmp_path)
    cao_log = tmp_path / "cao.log"
    _make_stub_command(
        bin_dir / "cao",
        f"""#!/usr/bin/env bash
set -euo pipefail
echo "$*" >> "{cao_log}"
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

    assert result.returncode == 0
    assert cao_log.read_text(encoding="utf-8").splitlines() == [
        "install code_supervisor",
        "install developer",
        "install reviewer",
    ]

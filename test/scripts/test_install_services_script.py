import subprocess
from pathlib import Path


def _read_install_script() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "install_services.sh"
    return script_path.read_text(encoding="utf-8")


def test_install_services_header_supports_stdin_execution() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "install_services.sh"
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


def test_skills_discovery_install_requires_interactive_terminal() -> None:
    script_content = _read_install_script()
    assert 'if [[ ! -t 0 || ! -t 1 ]]; then' in script_content
    assert "skills-installer 需要交互终端" in script_content


def test_skills_discovery_install_unsets_legacy_npm_init_module_env() -> None:
    script_content = _read_install_script()
    assert "unset npm_config_init_module NPM_CONFIG_INIT_MODULE" in script_content

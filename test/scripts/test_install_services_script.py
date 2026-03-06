import subprocess
from pathlib import Path


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

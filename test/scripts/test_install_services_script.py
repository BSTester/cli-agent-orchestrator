import subprocess
from pathlib import Path


def test_install_services_header_supports_stdin_execution() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    script_path = repo_root / "scripts" / "install_services.sh"
    header = "".join(script_path.read_text(encoding="utf-8").splitlines(keepends=True)[:12])

    result = subprocess.run(
        ["bash"],
        input=header,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "BASH_SOURCE[0]: unbound variable" not in result.stderr

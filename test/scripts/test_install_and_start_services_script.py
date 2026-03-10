import subprocess
import shutil
from pathlib import Path


def _make_script(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_install_and_start_services_uses_sibling_scripts(tmp_path: Path) -> None:
    original_script_path = (
        Path(__file__).resolve().parents[2] / "scripts" / "install_and_start_services.sh"
    )
    repo_root = tmp_path / "fake-repo"
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir(parents=True)
    log_file = tmp_path / "calls.log"

    shutil.copy2(original_script_path, scripts_dir / "install_and_start_services.sh")
    _make_script(
        scripts_dir / "install_services.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
echo "install:$PWD:$*" >> "{log_file}"
""",
    )
    _make_script(
        scripts_dir / "start_services.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
echo "start:$PWD:$*" >> "{log_file}"
""",
    )

    result = subprocess.run(
        ["bash", str(scripts_dir / "install_and_start_services.sh"), "--flag", "value"],
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert log_file.read_text(encoding="utf-8").splitlines() == [
        f"install:{tmp_path}:--flag value",
        f"start:{tmp_path}:--flag value",
    ]

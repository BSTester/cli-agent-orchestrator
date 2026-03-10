import subprocess
from pathlib import Path


def _make_script(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def test_install_and_start_services_uses_sibling_scripts(tmp_path: Path) -> None:
    repo_root = tmp_path / "fake-repo"
    scripts_dir = repo_root / "scripts"
    scripts_dir.mkdir(parents=True)
    log_file = tmp_path / "calls.log"

    _make_script(
        scripts_dir / "install_and_start_services.sh",
        """#!/usr/bin/env bash
set -euo pipefail

info() {
  echo "[INFO] $*"
}

main() {
  local root_dir
  if [[ -n "${BASH_SOURCE[0]-}" && "${BASH_SOURCE[0]}" != "bash" ]]; then
    root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  else
    root_dir="$(pwd)"
  fi

  info "兼容模式：先执行安装脚本，再执行启动脚本。"
  bash "$root_dir/scripts/install_services.sh" "$@"
  bash "$root_dir/scripts/start_services.sh" "$@"
}

main "$@"
""",
    )
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

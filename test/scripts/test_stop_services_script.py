import subprocess
from pathlib import Path


def _script_path() -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / "scripts" / "stop_services.sh"


def _make_stub_command(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _prepare_shell_basics(bin_dir: Path) -> None:
    _make_stub_command(
        bin_dir / "dirname",
        """#!/bin/bash
set -euo pipefail
/usr/bin/dirname "$@"
""",
    )


def _prepare_ps_fallback_tools(bin_dir: Path, os_name: str, ps_log: Path) -> None:
    _make_stub_command(
        bin_dir / "uname",
        f"""#!/bin/bash
set -euo pipefail
echo "{os_name}"
""",
    )
    _make_stub_command(
        bin_dir / "ps",
        f"""#!/bin/bash
set -euo pipefail
echo "$*" >> "{ps_log}"
echo "1234 cao-server"
""",
    )
    _make_stub_command(
        bin_dir / "awk",
        """#!/bin/bash
set -euo pipefail
while IFS= read -r _line; do
  :
done
echo "1234"
""",
    )


def test_stop_services_uses_macos_ps_flags_when_pgrep_unavailable(tmp_path: Path) -> None:
    script_path = _script_path()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ps_log = tmp_path / "ps.log"
    _prepare_shell_basics(bin_dir)
    _prepare_ps_fallback_tools(bin_dir, "Darwin", ps_log)

    result = subprocess.run(
        ["/bin/bash", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": str(bin_dir),
            "HOME": str(tmp_path),
        },
    )

    assert result.returncode == 0
    assert "ax -o pid= -o command=" in ps_log.read_text(encoding="utf-8")


def test_stop_services_uses_linux_ps_flags_when_pgrep_unavailable(tmp_path: Path) -> None:
    script_path = _script_path()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ps_log = tmp_path / "ps.log"
    _prepare_shell_basics(bin_dir)
    _prepare_ps_fallback_tools(bin_dir, "Linux", ps_log)

    result = subprocess.run(
        ["/bin/bash", str(script_path)],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": str(bin_dir),
            "HOME": str(tmp_path),
        },
    )

    assert result.returncode == 0
    assert "-eo pid=,args=" in ps_log.read_text(encoding="utf-8")

"""Tests for uninstall CLI command."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from cli_agent_orchestrator.cli.commands.uninstall import uninstall


def test_uninstall_removes_context_and_provider_artifacts() -> None:
    runner = CliRunner()

    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        context_dir = base / "context"
        qoder_dir = base / "qoder"
        codebuddy_dir = base / "codebuddy"
        copilot_dir = base / "copilot"
        q_dir = base / "q"
        kiro_dir = base / "kiro"

        for directory in [context_dir, qoder_dir, codebuddy_dir, copilot_dir, q_dir, kiro_dir]:
            directory.mkdir(parents=True, exist_ok=True)

        (context_dir / "demo-agent.md").write_text("demo")
        (qoder_dir / "demo-agent.md").write_text("demo")
        (codebuddy_dir / "demo-agent.md").write_text("demo")
        (copilot_dir / "demo-agent.md").write_text("demo")
        (q_dir / "demo-agent.json").write_text("demo")
        (kiro_dir / "demo-agent.json").write_text("demo")

        with (
            patch("cli_agent_orchestrator.cli.commands.uninstall.AGENT_CONTEXT_DIR", context_dir),
            patch("cli_agent_orchestrator.cli.commands.uninstall.QODER_AGENTS_DIR", qoder_dir),
            patch("cli_agent_orchestrator.cli.commands.uninstall.CODEBUDDY_AGENTS_DIR", codebuddy_dir),
            patch("cli_agent_orchestrator.cli.commands.uninstall.COPILOT_AGENTS_DIR", copilot_dir),
            patch("cli_agent_orchestrator.cli.commands.uninstall.Q_AGENTS_DIR", q_dir),
            patch("cli_agent_orchestrator.cli.commands.uninstall.KIRO_AGENTS_DIR", kiro_dir),
        ):
            result = runner.invoke(uninstall, ["demo-agent", "--provider", "all"])

        assert result.exit_code == 0
        assert not (context_dir / "demo-agent.md").exists()
        assert not (qoder_dir / "demo-agent.md").exists()
        assert not (codebuddy_dir / "demo-agent.md").exists()
        assert not (copilot_dir / "demo-agent.md").exists()
        assert not (q_dir / "demo-agent.json").exists()
        assert not (kiro_dir / "demo-agent.json").exists()


def test_uninstall_provider_specific_only_removes_target_provider_artifact() -> None:
    runner = CliRunner()

    with tempfile.TemporaryDirectory() as tmpdir:
        base = Path(tmpdir)
        context_dir = base / "context"
        qoder_dir = base / "qoder"
        copilot_dir = base / "copilot"
        context_dir.mkdir(parents=True, exist_ok=True)
        qoder_dir.mkdir(parents=True, exist_ok=True)
        copilot_dir.mkdir(parents=True, exist_ok=True)

        (context_dir / "demo-agent.md").write_text("demo")
        (qoder_dir / "demo-agent.md").write_text("demo")
        (copilot_dir / "demo-agent.md").write_text("demo")

        with (
            patch("cli_agent_orchestrator.cli.commands.uninstall.AGENT_CONTEXT_DIR", context_dir),
            patch("cli_agent_orchestrator.cli.commands.uninstall.QODER_AGENTS_DIR", qoder_dir),
            patch("cli_agent_orchestrator.cli.commands.uninstall.COPILOT_AGENTS_DIR", copilot_dir),
        ):
            result = runner.invoke(uninstall, ["demo-agent", "--provider", "qoder_cli"])

        assert result.exit_code == 0
        assert not (context_dir / "demo-agent.md").exists()
        assert not (qoder_dir / "demo-agent.md").exists()
        assert (copilot_dir / "demo-agent.md").exists()

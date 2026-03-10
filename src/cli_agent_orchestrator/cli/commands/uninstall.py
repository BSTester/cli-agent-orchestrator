"""Uninstall command for CLI Agent Orchestrator."""

from pathlib import Path

import click

from cli_agent_orchestrator.constants import (
    AGENT_CONTEXT_DIR,
    CODEBUDDY_AGENTS_DIR,
    COPILOT_AGENTS_DIR,
    KIRO_AGENTS_DIR,
    PROVIDERS,
    QODER_AGENTS_DIR,
    Q_AGENTS_DIR,
)

ALL_PROVIDERS = "all"


def _safe_agent_filename(agent_name: str) -> str:
    return agent_name.replace("/", "__")


def _remove_if_exists(file_path: Path) -> bool:
    if not file_path.exists():
        return False
    file_path.unlink()
    return True


@click.command()
@click.argument("agent_name")
@click.option(
    "--provider",
    type=click.Choice([ALL_PROVIDERS, *PROVIDERS]),
    default=ALL_PROVIDERS,
    help=(
        f"Provider to uninstall for (default: {ALL_PROVIDERS}); "
        f"use one of: {', '.join(PROVIDERS)}"
    ),
)
def uninstall(agent_name: str, provider: str):
    """Uninstall an agent profile and provider-specific artifacts."""
    try:
        normalized_name = agent_name.strip()
        if not normalized_name:
            raise click.ClickException("Agent name cannot be empty")

        safe_name = _safe_agent_filename(normalized_name)
        removed_paths: list[Path] = []

        # Always remove CAO context file as part of uninstall (reverse of install)
        context_file = AGENT_CONTEXT_DIR / f"{safe_name}.md"
        if _remove_if_exists(context_file):
            removed_paths.append(context_file)

        target_providers = PROVIDERS if provider == ALL_PROVIDERS else [provider]
        for target_provider in target_providers:
            if target_provider == "q_cli":
                candidate = Q_AGENTS_DIR / f"{safe_name}.json"
            elif target_provider == "kiro_cli":
                candidate = KIRO_AGENTS_DIR / f"{safe_name}.json"
            elif target_provider == "qoder_cli":
                candidate = QODER_AGENTS_DIR / f"{safe_name}.md"
            elif target_provider == "codebuddy":
                candidate = CODEBUDDY_AGENTS_DIR / f"{safe_name}.md"
            elif target_provider == "copilot":
                candidate = COPILOT_AGENTS_DIR / f"{safe_name}.md"
            else:
                # Runtime-injected providers don't have local artifact files
                continue

            if _remove_if_exists(candidate):
                removed_paths.append(candidate)

        click.echo(f"✓ Agent '{normalized_name}' uninstalled")
        if removed_paths:
            for path in removed_paths:
                click.echo(f"✓ Removed: {path}")
        else:
            click.echo("✓ No local artifacts found to remove")

    except click.ClickException:
        raise
    except Exception as exc:
        raise click.ClickException(f"Failed to uninstall agent: {exc}")

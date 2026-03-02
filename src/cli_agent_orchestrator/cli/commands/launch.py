"""Launch command for CLI Agent Orchestrator CLI."""

import os
import subprocess
from typing import Optional

import click
import requests

from cli_agent_orchestrator.constants import DEFAULT_PROVIDER, PROVIDERS, SERVER_HOST, SERVER_PORT
from cli_agent_orchestrator.utils.agent_profiles import load_agent_profile

# Providers that require workspace folder access
PROVIDERS_REQUIRING_WORKSPACE_ACCESS = {
    "claude_code",
    "codex",
    "kiro_cli",
    "qoder_cli",
    "codebuddy",
    "copilot",
}


def _resolve_provider(agent_name: str, provider: Optional[str]) -> str:
    """Resolve provider from explicit option -> profile field -> default."""
    if provider:
        return provider

    try:
        profile = load_agent_profile(agent_name)
        if profile.provider is not None:
            return profile.provider.value
    except Exception:
        # Keep backward-compatible behavior when profile cannot be loaded.
        pass

    return DEFAULT_PROVIDER


@click.command()
@click.option("--agents", required=True, help="Agent profile to launch")
@click.option("--session-name", help="Name of the session (default: auto-generated)")
@click.option("--headless", is_flag=True, help="Launch in detached mode")
@click.option(
    "--provider", default=None, help="Provider to use (default: profile provider or system default)"
)
@click.option(
    "--working-directory",
    default=None,
    help="Working directory to launch the agent in (default: current directory)",
)
@click.option("--yolo", is_flag=True, help="Skip workspace trust confirmation")
def launch(agents, session_name, headless, provider, working_directory, yolo):
    """Launch cao session with specified agent profile."""
    try:
        resolved_provider = _resolve_provider(agents, provider)

        # Validate provider
        if resolved_provider not in PROVIDERS:
            raise click.ClickException(
                f"Invalid provider '{resolved_provider}'. Available providers: {', '.join(PROVIDERS)}"
            )
        resolved_working_directory = os.path.realpath(working_directory or os.getcwd())
        if not os.path.isdir(resolved_working_directory):
            raise click.ClickException(
                f"Working directory does not exist or is not a directory: {resolved_working_directory}"
            )

        # Ask for workspace trust confirmation for providers that need it.
        # Note: CAO itself does not access the workspace — it is the underlying
        # provider (e.g. claude_code, codex) that reads, writes, and executes
        # commands in the workspace directory.
        if resolved_provider in PROVIDERS_REQUIRING_WORKSPACE_ACCESS and not yolo:
            click.echo(
                f"The underlying provider ({resolved_provider}) will be trusted to perform all actions "
                f"(read, write, and execute) in:\n"
                f"  {resolved_working_directory}\n\n"
                f"To skip this confirmation, use: cao launch --yolo\n"
            )
            if not click.confirm("Do you trust all the actions in this folder?", default=True):
                raise click.ClickException("Launch cancelled by user")

        # Call API to create session
        url = f"http://{SERVER_HOST}:{SERVER_PORT}/sessions"
        params = {
            "provider": resolved_provider,
            "agent_profile": agents,
            "working_directory": resolved_working_directory,
        }
        if session_name:
            params["session_name"] = session_name

        response = requests.post(url, params=params)
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError:
            if response.status_code == 400 and "Working directory not allowed" in response.text:
                fallback_params = {
                    "provider": resolved_provider,
                    "agent_profile": agents,
                }
                if session_name:
                    fallback_params["session_name"] = session_name

                click.echo(
                    "Working directory is outside allowed scope; retrying launch without "
                    "working_directory parameter."
                )
                response = requests.post(url, params=fallback_params)
                response.raise_for_status()
            else:
                raise

        terminal = response.json()

        click.echo(f"Session created: {terminal['session_name']}")
        click.echo(f"Terminal created: {terminal['name']}")

        # Attach to tmux session unless headless
        if not headless:
            subprocess.run(["tmux", "attach-session", "-t", terminal["session_name"]])

    except requests.exceptions.RequestException as e:
        raise click.ClickException(f"Failed to connect to cao-server: {str(e)}")
    except Exception as e:
        raise click.ClickException(str(e))

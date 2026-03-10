"""Install command for CLI Agent Orchestrator."""

from importlib import resources
from pathlib import Path

import click
import requests

from cli_agent_orchestrator.constants import (
    AGENT_CONTEXT_DIR,
    COPILOT_AGENTS_DIR,
    KIRO_AGENTS_DIR,
    LOCAL_AGENT_STORE_DIR,
    PROVIDERS,
    QODER_AGENTS_DIR,
    Q_AGENTS_DIR,
)
from cli_agent_orchestrator.models.kiro_agent import KiroAgentConfig
from cli_agent_orchestrator.models.provider import ProviderType
from cli_agent_orchestrator.models.q_agent import QAgentConfig
from cli_agent_orchestrator.utils.agent_profiles import load_agent_profile

ALL_PROVIDERS = "all"

RUNTIME_INJECTED_PROVIDERS = {
    ProviderType.CLAUDE_CODE.value,
    ProviderType.CODEX.value,
    ProviderType.CODEBUDDY.value,
    ProviderType.OPENCLAW.value,
}

DEFAULT_GLOBAL_INSTALL_PROVIDERS = [
    provider_name
    for provider_name in PROVIDERS
    if provider_name not in RUNTIME_INJECTED_PROVIDERS
]


def _download_agent(source: str) -> str:
    """Download or copy agent file to local store. Returns agent name."""
    LOCAL_AGENT_STORE_DIR.mkdir(parents=True, exist_ok=True)

    # Handle URL
    if source.startswith("http://") or source.startswith("https://"):
        response = requests.get(source)
        response.raise_for_status()
        content = response.text

        # Extract filename from URL
        filename = Path(source).name
        if not filename.endswith(".md"):
            raise ValueError("URL must point to a .md file")

        dest_file = LOCAL_AGENT_STORE_DIR / filename
        dest_file.write_text(content)

        # Return agent name (filename without .md)
        return dest_file.stem

    # Handle file path
    source_path = Path(source)
    if source_path.exists():
        if not source_path.suffix == ".md":
            raise ValueError("File must be a .md file")

        dest_file = LOCAL_AGENT_STORE_DIR / source_path.name
        dest_file.write_text(source_path.read_text())

        # Return agent name (filename without .md)
        return dest_file.stem

    raise FileNotFoundError(f"Source not found: {source}")


@click.command()
@click.argument("agent_source")
@click.option(
    "--provider",
    type=click.Choice([ALL_PROVIDERS, *PROVIDERS]),
    default=ALL_PROVIDERS,
    help=(
        f"Provider to install for (default: {ALL_PROVIDERS} global-install providers); "
        f"use one of: {', '.join(PROVIDERS)}"
    ),
)
def install(agent_source: str, provider: str):
    """
    Install an agent from local store, built-in store, URL, or file path.

    AGENT_SOURCE can be:
    - Agent name (e.g., 'developer', 'code_supervisor')
    - File path (e.g., './my-agent.md', '/path/to/agent.md')
    - URL (e.g., 'https://example.com/agent.md')
    """
    try:
        # Detect source type and handle accordingly
        if agent_source.startswith("http://") or agent_source.startswith("https://"):
            # Download from URL
            agent_name = _download_agent(agent_source)
            click.echo(f"✓ Downloaded agent from URL to local store")
        elif Path(agent_source).exists():
            # Copy from file path
            agent_name = _download_agent(agent_source)
            click.echo(f"✓ Copied agent from file to local store")
        else:
            # Treat as agent name
            agent_name = agent_source

        # Load agent profile using existing Pydantic parser
        profile = load_agent_profile(agent_name)

        # Ensure directories exist
        AGENT_CONTEXT_DIR.mkdir(parents=True, exist_ok=True)

        # Determine source for context file
        local_profile = LOCAL_AGENT_STORE_DIR / f"{agent_name}.md"
        if local_profile.exists():
            source_file = local_profile
        else:
            agent_store = resources.files("cli_agent_orchestrator.agent_store")
            source_file = agent_store / f"{agent_name}.md"

        # Copy markdown file to agent-context directory
        dest_file = AGENT_CONTEXT_DIR / f"{profile.name}.md"
        with open(source_file, "r") as src:
            dest_file.write_text(src.read())

        # Build allowedTools default if not specified
        allowed_tools = profile.allowedTools
        if allowed_tools is None:
            # Default: allow all built-in tools and all MCP server tools
            allowed_tools = ["@builtin", "fs_*", "execute_bash"]
            if profile.mcpServers:
                for server_name in profile.mcpServers.keys():
                    allowed_tools.append(f"@{server_name}")

        # Create provider-specific agent artifacts
        safe_filename = profile.name.replace("/", "__")
        target_providers = (
            DEFAULT_GLOBAL_INSTALL_PROVIDERS if provider == ALL_PROVIDERS else [provider]
        )

        installed_files = []
        runtime_injected = []

        for target_provider in target_providers:
            if target_provider == ProviderType.Q_CLI.value:
                Q_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
                agent_config = QAgentConfig(
                    name=profile.name,
                    description=profile.description,
                    tools=profile.tools if profile.tools is not None else ["*"],
                    allowedTools=allowed_tools,
                    resources=[f"file://{dest_file.absolute()}"],
                    prompt=profile.prompt or profile.system_prompt,
                    mcpServers=profile.mcpServers,
                    toolAliases=profile.toolAliases,
                    toolsSettings=profile.toolsSettings,
                    hooks=profile.hooks,
                    model=profile.model,
                )
                agent_file = Q_AGENTS_DIR / f"{safe_filename}.json"
                with open(agent_file, "w") as f:
                    f.write(agent_config.model_dump_json(indent=2, exclude_none=True))
                installed_files.append((target_provider, agent_file))
                continue

            if target_provider == ProviderType.KIRO_CLI.value:
                KIRO_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
                agent_config = KiroAgentConfig(
                    name=profile.name,
                    description=profile.description,
                    tools=profile.tools if profile.tools is not None else ["*"],
                    allowedTools=allowed_tools,
                    resources=[f"file://{dest_file.absolute()}"],
                    prompt=profile.prompt or profile.system_prompt,
                    mcpServers=profile.mcpServers,
                    toolAliases=profile.toolAliases,
                    toolsSettings=profile.toolsSettings,
                    hooks=profile.hooks,
                    model=profile.model,
                )
                agent_file = KIRO_AGENTS_DIR / f"{safe_filename}.json"
                with open(agent_file, "w") as f:
                    f.write(agent_config.model_dump_json(indent=2, exclude_none=True))
                installed_files.append((target_provider, agent_file))
                continue

            if target_provider == ProviderType.COPILOT.value:
                COPILOT_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
                agent_file = COPILOT_AGENTS_DIR / f"{safe_filename}.md"
                agent_file.write_text(source_file.read_text())
                installed_files.append((target_provider, agent_file))
                continue

            if target_provider == ProviderType.QODER_CLI.value:
                QODER_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
                agent_file = QODER_AGENTS_DIR / f"{safe_filename}.md"
                agent_file.write_text(source_file.read_text())
                installed_files.append((target_provider, agent_file))
                continue

            if target_provider in RUNTIME_INJECTED_PROVIDERS:
                runtime_injected.append(target_provider)
                continue

        click.echo(f"✓ Agent '{profile.name}' installed successfully")
        click.echo(f"✓ Context file: {dest_file}")
        for target_provider, agent_file in installed_files:
            click.echo(f"✓ {target_provider} agent: {agent_file}")

        if runtime_injected:
            click.echo(
                "✓ Runtime-injected providers (no local agent file needed): "
                + ", ".join(runtime_injected)
            )

        if provider == ALL_PROVIDERS:
            click.echo(f"✓ Installed for providers: {', '.join(target_providers)}")

    except FileNotFoundError as e:
        click.echo(f"Error: {e}", err=True)
        return
    except requests.RequestException as e:
        click.echo(f"Error: Failed to download agent: {e}", err=True)
        return
    except Exception as e:
        click.echo(f"Error: Failed to install agent: {e}", err=True)
        return

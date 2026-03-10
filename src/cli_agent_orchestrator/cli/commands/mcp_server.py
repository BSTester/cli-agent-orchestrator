"""MCP server command for CLI Agent Orchestrator CLI."""

import click

from cli_agent_orchestrator.mcp_server.server import main as run_mcp_server


@click.command(name="mcp-server")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "http"], case_sensitive=False),
    default="stdio",
    show_default=True,
    help="Transport protocol for the MCP server.",
)
@click.option("--host", help="HTTP host to bind when --transport=http.")
@click.option("--port", type=int, help="HTTP port to bind when --transport=http.")
@click.option("--path", help="HTTP path to mount when --transport=http.")
def mcp_server(
    transport: str,
    host: str | None,
    port: int | None,
    path: str | None,
):
    """Start the CAO MCP server."""
    run_mcp_server(transport=transport.lower(), host=host, port=port, path=path)

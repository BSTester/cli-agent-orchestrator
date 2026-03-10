"""Tests for mcp-server command."""

from unittest.mock import patch

from click.testing import CliRunner

from cli_agent_orchestrator.cli.commands.mcp_server import mcp_server


def test_mcp_server_command():
    """Test that mcp-server command calls run_mcp_server."""
    runner = CliRunner()

    with patch("cli_agent_orchestrator.cli.commands.mcp_server.run_mcp_server") as mock_run:
        result = runner.invoke(mcp_server)

        assert result.exit_code == 0
        mock_run.assert_called_once_with(
            transport="stdio",
            host=None,
            port=None,
            path=None,
        )


def test_mcp_server_command_supports_http_transport_options():
    """Test that mcp-server command forwards HTTP transport options."""
    runner = CliRunner()

    with patch("cli_agent_orchestrator.cli.commands.mcp_server.run_mcp_server") as mock_run:
        result = runner.invoke(
            mcp_server,
            ["--transport", "http", "--host", "0.0.0.0", "--port", "8080", "--path", "/mcp"],
        )

        assert result.exit_code == 0
        mock_run.assert_called_once_with(
            transport="http",
            host="0.0.0.0",
            port=8080,
            path="/mcp",
        )


@patch("cli_agent_orchestrator.mcp_server.server.mcp.run")
def test_mcp_server_main_disables_banner(mock_run):
    """Ensure main enables banner output for stdio transport."""
    from cli_agent_orchestrator.mcp_server.server import main

    main()

    mock_run.assert_called_once_with(show_banner=True, log_level="INFO")


@patch("cli_agent_orchestrator.mcp_server.server.mcp.run")
def test_mcp_server_main_supports_http_transport(mock_run):
    """Ensure main can start the MCP server over HTTP."""
    from cli_agent_orchestrator.mcp_server.server import main

    main(transport="http", host="0.0.0.0", port=8080, path="/mcp")

    mock_run.assert_called_once_with(
        transport="http",
        host="0.0.0.0",
        port=8080,
        path="/mcp",
        show_banner=True,
        log_level="INFO",
    )


@patch("cli_agent_orchestrator.mcp_server.server.main")
def test_cao_mcp_server_cli_entrypoint_parses_http_args(mock_main):
    """Ensure the standalone cao-mcp-server script can parse HTTP args."""
    from cli_agent_orchestrator.mcp_server.server import cli_main

    cli_main(["--transport", "http", "--host", "127.0.0.1", "--port", "9000"])

    mock_main.assert_called_once_with(
        transport="http",
        host="127.0.0.1",
        port=9000,
        path=None,
    )

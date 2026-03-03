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
        mock_run.assert_called_once()


@patch("cli_agent_orchestrator.mcp_server.server.mcp.run")
def test_mcp_server_main_disables_banner(mock_run):
    """Ensure main disables banner output for stdio transport."""
    from cli_agent_orchestrator.mcp_server.server import main

    main()

    mock_run.assert_called_once_with(show_banner=False, log_level="INFO")

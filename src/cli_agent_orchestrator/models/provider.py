from enum import Enum


class ProviderType(str, Enum):
    """Provider type enumeration."""

    SHELL = "shell"
    Q_CLI = "q_cli"
    KIRO_CLI = "kiro_cli"
    CLAUDE_CODE = "claude_code"
    CODEX = "codex"
    QODER_CLI = "qoder_cli"
    CODEBUDDY = "codebuddy"
    COPILOT = "copilot"
    OPENCLAW = "openclaw"

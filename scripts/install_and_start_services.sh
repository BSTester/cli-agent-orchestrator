#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/.runtime"
LOG_DIR="$RUNTIME_DIR/logs"
PID_DIR="$RUNTIME_DIR/pids"

SERVER_PID_FILE="$PID_DIR/cao-server.pid"
PANEL_PID_FILE="$PID_DIR/cao-control-panel.pid"
SERVER_LOG_FILE="$LOG_DIR/cao-server.log"
PANEL_LOG_FILE="$LOG_DIR/cao-control-panel.log"

SERVER_HOST="${SERVER_HOST:-localhost}"
SERVER_PORT="${SERVER_PORT:-9889}"
CONTROL_PANEL_HOST="${CONTROL_PANEL_HOST:-localhost}"
CONTROL_PANEL_PORT="${CONTROL_PANEL_PORT:-8000}"
CAO_SERVER_URL="${CAO_SERVER_URL:-http://$SERVER_HOST:$SERVER_PORT}"
CAO_CONSOLE_PASSWORD="${CAO_CONSOLE_PASSWORD:-admin}"

CAO_REPO_REF="${CAO_REPO_REF:-main}"
CAO_REPO_URL="${CAO_REPO_URL:-https://github.com/BSTester/cli-agent-orchestrator.git}"
CAO_TOOL_SPEC="git+${CAO_REPO_URL}@${CAO_REPO_REF}"

# Skills discovery integration
SKILLS_DISCOVERY_SPEC="${SKILLS_DISCOVERY_SPEC:-@Kamalnrf/claude-plugins/skills-discovery}"
SKILLS_INSTALLER_CMD="${SKILLS_INSTALLER_CMD:-skills-installer}"

# npm package specs (allow overriding by environment variables)
CODEX_NPM_SPEC="${CODEX_NPM_SPEC:-@openai/codex}"
CLAUDE_CODE_NPM_SPEC="${CLAUDE_CODE_NPM_SPEC:-@anthropic-ai/claude-code}"
KIRO_CLI_NPM_SPEC="${KIRO_CLI_NPM_SPEC:-kiro-cli}"
QODERCLI_NPM_SPEC="${QODERCLI_NPM_SPEC:-qoder-cli}"
CODEBUDDY_NPM_SPEC="${CODEBUDDY_NPM_SPEC:-codebuddy}"
COPILOT_NPM_SPEC="${COPILOT_NPM_SPEC:-@github/copilot}"

mkdir -p "$LOG_DIR" "$PID_DIR"

info() {
  echo "[INFO] $*"
}

warn() {
  echo "[WARN] $*"
}

die() {
  echo "[ERROR] $*" >&2
  exit 1
}

require_cmd() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || die "缺少命令: $cmd"
}

has_cmd() {
  command -v "$1" >/dev/null 2>&1
}

run_privileged() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
    return
  fi

  if has_cmd sudo; then
    sudo "$@"
    return
  fi

  die "需要管理员权限执行: $*（请安装 sudo 或使用 root 运行）"
}

install_packages_linux() {
  local packages=("$@")

  if has_cmd apt-get; then
    run_privileged apt-get update
    run_privileged apt-get install -y "${packages[@]}"
    return
  fi

  if has_cmd dnf; then
    run_privileged dnf install -y "${packages[@]}"
    return
  fi

  if has_cmd yum; then
    run_privileged yum install -y "${packages[@]}"
    return
  fi

  if has_cmd zypper; then
    run_privileged zypper --non-interactive install "${packages[@]}"
    return
  fi

  if has_cmd pacman; then
    run_privileged pacman -Sy --noconfirm "${packages[@]}"
    return
  fi

  die "无法识别 Linux 包管理器，请手动安装: ${packages[*]}"
}

install_packages_macos() {
  local packages=("$@")
  if ! has_cmd brew; then
    die "macOS 下未检测到 Homebrew，请先安装 brew 后重试。"
  fi
  brew update
  brew install "${packages[@]}"
}

ensure_basic_tools() {
  local missing=()
  for cmd in curl git; do
    if ! has_cmd "$cmd"; then
      missing+=("$cmd")
    fi
  done

  if [[ "${#missing[@]}" -eq 0 ]]; then
    return
  fi

  info "检测到缺少基础命令: ${missing[*]}，尝试自动安装..."
  case "$(uname -s)" in
    Darwin)
      install_packages_macos "${missing[@]}"
      ;;
    Linux)
      install_packages_linux "${missing[@]}"
      ;;
    *)
      die "当前系统不支持自动安装基础命令，请手动安装: ${missing[*]}"
      ;;
  esac
}

ensure_python3() {
  if has_cmd python3; then
    return
  fi

  info "未检测到 python3，尝试自动安装..."
  case "$(uname -s)" in
    Darwin)
      install_packages_macos python
      ;;
    Linux)
      install_packages_linux python3 python3-venv
      ;;
    *)
      die "当前系统不支持自动安装 Python3，请手动安装 Python 3.10+"
      ;;
  esac
}

ensure_nodejs() {
  if has_cmd node && has_cmd npm && has_cmd npx; then
    return
  fi

  info "未检测到 Node.js/npm，尝试自动安装..."
  case "$(uname -s)" in
    Darwin)
      install_packages_macos node
      ;;
    Linux)
      if has_cmd apt-get; then
        install_packages_linux nodejs npm
      else
        install_packages_linux nodejs
      fi
      ;;
    *)
      die "当前系统不支持自动安装 Node.js，请手动安装 Node.js 18+"
      ;;
  esac

  has_cmd node || die "Node.js 安装失败，请手动安装后重试。"
  has_cmd npm || die "npm 安装失败，请手动安装后重试。"
  has_cmd npx || die "npx 不可用，请手动安装后重试。"
}

ensure_uv() {
  if has_cmd uv; then
    return
  fi

  info "未检测到 uv，正在安装..."
  require_cmd curl
  curl -LsSf https://astral.sh/uv/install.sh | sh

  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  has_cmd uv || die "uv 安装完成但当前 shell 未找到 uv，请手动执行: source ~/.bashrc 或 source ~/.zshrc"
}

ensure_tmux() {
  if has_cmd tmux; then
    return
  fi

  info "未检测到 tmux，尝试自动安装..."
  case "$(uname -s)" in
    Darwin)
      install_packages_macos tmux
      ;;
    Linux)
      install_packages_linux tmux
      ;;
    *)
      die "未检测到 tmux，且当前系统不支持自动安装，请手动安装 tmux 3.2+"
      ;;
  esac

  has_cmd tmux || die "tmux 安装失败，请手动安装后重试。"
}

ensure_tool_path() {
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$(npm config get prefix 2>/dev/null || echo "$HOME/.npm-global")/bin:$PATH"
}

install_npm_cli_if_missing() {
  local cmd="$1"
  local npm_spec="$2"

  if has_cmd "$cmd"; then
    info "$cmd 已安装，跳过。"
    return
  fi

  info "安装 $cmd (npm: $npm_spec)..."
  npm install -g "$npm_spec"
  ensure_tool_path

  has_cmd "$cmd" || die "$cmd 安装失败，请检查 npm 包名（当前: $npm_spec）"
}

install_agent_clis() {
  ensure_nodejs
  ensure_tool_path

  install_npm_cli_if_missing codex "$CODEX_NPM_SPEC"
  install_npm_cli_if_missing claude "$CLAUDE_CODE_NPM_SPEC"
  install_npm_cli_if_missing kiro-cli "$KIRO_CLI_NPM_SPEC"
  install_npm_cli_if_missing qodercli "$QODERCLI_NPM_SPEC"
  install_npm_cli_if_missing codebuddy "$CODEBUDDY_NPM_SPEC"
  install_npm_cli_if_missing copilot "$COPILOT_NPM_SPEC"
}

install_skills_discovery_for_all_agents() {
  ensure_nodejs
  info "安装 skills-discovery 服务（所有支持 skills 的 agent 共用）: $SKILLS_DISCOVERY_SPEC"
  npx -y "$SKILLS_INSTALLER_CMD" install "$SKILLS_DISCOVERY_SPEC"
}

install_cao_tool() {
  info "安装/升级 CLI Agent Orchestrator 工具: $CAO_TOOL_SPEC"
  uv tool install "$CAO_TOOL_SPEC" --upgrade
  ensure_tool_path

  require_cmd cao
  require_cmd cao-server
  require_cmd cao-control-panel
}

is_running_from_pid() {
  local pid_file="$1"
  if [[ ! -f "$pid_file" ]]; then
    return 1
  fi

  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  [[ -n "$pid" ]] || return 1

  if kill -0 "$pid" >/dev/null 2>&1; then
    return 0
  fi

  rm -f "$pid_file"
  return 1
}

start_service() {
  local name="$1"
  local pid_file="$2"
  local log_file="$3"
  shift 3

  if is_running_from_pid "$pid_file"; then
    info "$name 已在运行 (pid=$(cat "$pid_file"))"
    return
  fi

  info "启动 $name ..."
  nohup "$@" >"$log_file" 2>&1 &
  local pid=$!
  echo "$pid" >"$pid_file"
  info "$name 启动完成 (pid=$pid, log=$log_file)"
}

wait_for_health() {
  local name="$1"
  local url="$2"
  local retries="${3:-40}"
  local sleep_seconds="${4:-1}"

  info "等待 $name 健康检查通过: $url"

  for ((i = 1; i <= retries; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      info "$name 健康检查通过。"
      return
    fi
    sleep "$sleep_seconds"
  done

  die "$name 健康检查超时，请查看日志。"
}

main() {
  require_cmd bash

  ensure_basic_tools
  ensure_python3

  ensure_uv
  ensure_nodejs
  ensure_tmux
  install_cao_tool
  install_agent_clis
  install_skills_discovery_for_all_agents

  start_service \
    "cao-server" \
    "$SERVER_PID_FILE" \
    "$SERVER_LOG_FILE" \
    env SERVER_HOST="$SERVER_HOST" SERVER_PORT="$SERVER_PORT" cao-server

  wait_for_health "cao-server" "http://$SERVER_HOST:$SERVER_PORT/health"

  start_service \
    "cao-control-panel" \
    "$PANEL_PID_FILE" \
    "$PANEL_LOG_FILE" \
    env CONTROL_PANEL_HOST="$CONTROL_PANEL_HOST" CONTROL_PANEL_PORT="$CONTROL_PANEL_PORT" CAO_SERVER_URL="$CAO_SERVER_URL" CAO_CONSOLE_PASSWORD="$CAO_CONSOLE_PASSWORD" cao-control-panel

  wait_for_health "cao-control-panel" "http://$CONTROL_PANEL_HOST:$CONTROL_PANEL_PORT/health"

  info "全部服务已启动。"
  echo
  echo "访问地址:"
  echo "- 控制面板: http://$CONTROL_PANEL_HOST:$CONTROL_PANEL_PORT"
  echo "- 后端健康检查: http://$SERVER_HOST:$SERVER_PORT/health"
  echo
  echo "日志文件:"
  echo "- $SERVER_LOG_FILE"
  echo "- $PANEL_LOG_FILE"
  echo
  echo "PID 文件:"
  echo "- $SERVER_PID_FILE"
  echo "- $PANEL_PID_FILE"
}

main "$@"

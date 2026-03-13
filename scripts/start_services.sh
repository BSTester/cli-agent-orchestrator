#!/usr/bin/env bash
set -euo pipefail

SERVER_HOST="${SERVER_HOST:-localhost}"
SERVER_PORT="${SERVER_PORT:-9889}"
CONTROL_PANEL_HOST="${CONTROL_PANEL_HOST:-localhost}"
CONTROL_PANEL_PORT="${CONTROL_PANEL_PORT:-8000}"
CAO_SERVER_URL="${CAO_SERVER_URL:-http://$SERVER_HOST:$SERVER_PORT}"
CAO_CONSOLE_PASSWORD="${CAO_CONSOLE_PASSWORD:-admin}"

info() {
  echo "[INFO] $*"
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
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1
}

openclaw_gateway_service_loaded() {
  local status_output="$1"
  [[ -n "$status_output" ]] || return 1

  grep -Eiq 'Service:[[:space:]]*.*\((enabled|loaded|registered)\)' <<<"$status_output"
}

openclaw_gateway_service_unavailable() {
  local status_output="$1"
  [[ -n "$status_output" ]] || return 1

  grep -Eiq 'systemd user services are unavailable|run the gateway in the foreground|Failed to connect to bus|System has not been booted with systemd|Service:[[:space:]]*.*\((missing|unavailable|disabled)\)' <<<"$status_output"
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

openclaw_gateway_running() {
  local status_output="$1"
  [[ -n "$status_output" ]] || return 1
  grep -Eiq 'Runtime:[[:space:]]*running\b|state[[:space:]]+active\b|sub[[:space:]]+running\b' <<<"$status_output"
}

wait_for_openclaw_gateway() {
  local retries="${1:-30}"
  local sleep_seconds="${2:-1}"
  local status_output=""

  info "等待 OpenClaw gateway 就绪..."

  for ((i = 1; i <= retries; i++)); do
    status_output="$(openclaw gateway status 2>&1 || true)"
    if openclaw_gateway_running "$status_output"; then
      info "OpenClaw gateway 已就绪。"
      return
    fi
    sleep "$sleep_seconds"
  done

  die "OpenClaw gateway 启动超时，请查看 gateway 日志。"
}

ensure_process_started() {
  local name="$1"
  local pid_file="$2"
  local startup_delay="${3:-0.2}"

  sleep "$startup_delay"
  if is_running_from_pid "$pid_file"; then
    return
  fi

  die "$name 进程已退出，请查看日志。"
}

install_openclaw_gateway_service_if_possible() {
  if ! has_cmd openclaw; then
    return 1
  fi

  if [[ "$(uname -s)" == "Linux" ]] && ! has_cmd systemctl; then
    return 1
  fi

  info "尝试安装 OpenClaw gateway 服务..."
  if ! openclaw gateway install --force >/dev/null 2>&1; then
    return 1
  fi

  return 0
}

start_openclaw_gateway_foreground() {
  local pid_file="$1"
  local log_file="$2"

  if is_running_from_pid "$pid_file"; then
    info "openclaw-gateway 已在运行 (pid=$(cat "$pid_file"))"
    return
  fi

  info "以脚本托管模式启动 OpenClaw gateway ..."
  start_service \
    "openclaw-gateway" \
    "$pid_file" \
    "$log_file" \
    openclaw gateway

  ensure_process_started "OpenClaw gateway" "$pid_file"
  info "OpenClaw gateway 已进入后台启动流程，继续启动 CAO 其余服务。"
}

ensure_openclaw_gateway() {
  local gateway_pid_file="$1"
  local gateway_log_file="$2"
  local gateway_enabled="${OPENCLAW_GATEWAY_ENABLE:-1}"
  if [[ "$gateway_enabled" != "1" ]]; then
    info "已跳过 OpenClaw gateway 启动（OPENCLAW_GATEWAY_ENABLE=$gateway_enabled）。"
    return
  fi

  require_cmd openclaw

  info "检查 OpenClaw gateway 状态..."

  local status_output
  status_output="$(openclaw gateway status 2>&1 || true)"

  if openclaw_gateway_running "$status_output"; then
    info "OpenClaw gateway 已在运行，执行重启。"
    if openclaw gateway restart >/dev/null 2>&1; then
      wait_for_openclaw_gateway
      return
    fi

    warn "OpenClaw gateway 服务重启失败，改用脚本托管模式。"
    start_openclaw_gateway_foreground "$gateway_pid_file" "$gateway_log_file"
    return
  fi

  if ! openclaw_gateway_service_loaded "$status_output"; then
    info "OpenClaw gateway 服务未安装或不可用，尝试补装。"
    if install_openclaw_gateway_service_if_possible; then
      status_output="$(openclaw gateway status 2>&1 || true)"
    fi
  fi

  if openclaw_gateway_service_loaded "$status_output"; then
    info "OpenClaw gateway 未运行，执行启动。"
    if openclaw gateway start >/dev/null 2>&1; then
      wait_for_openclaw_gateway
      return
    fi

    warn "OpenClaw gateway 服务启动失败，改用脚本托管模式。"
  elif openclaw_gateway_service_unavailable "$status_output"; then
    info "当前环境不支持 OpenClaw gateway 服务监管，改用脚本托管模式。"
  else
    warn "OpenClaw gateway 服务状态未知，改用脚本托管模式。"
  fi

  start_openclaw_gateway_foreground "$gateway_pid_file" "$gateway_log_file"
}

main() {
  local root_dir
  if [[ -n "${BASH_SOURCE[0]-}" && "${BASH_SOURCE[0]}" != "bash" ]]; then
    root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  else
    root_dir="$(pwd)"
  fi

  local runtime_dir="${CAO_RUNTIME_DIR:-$root_dir/.runtime}"
  local log_dir="$runtime_dir/logs"
  local pid_dir="$runtime_dir/pids"
  local server_pid_file="$pid_dir/cao-server.pid"
  local panel_pid_file="$pid_dir/cao-control-panel.pid"
  local gateway_pid_file="$pid_dir/openclaw-gateway.pid"
  local server_log_file="$log_dir/cao-server.log"
  local panel_log_file="$log_dir/cao-control-panel.log"
  local gateway_log_file="$log_dir/openclaw-gateway.log"

  mkdir -p "$log_dir" "$pid_dir"
  cd "$root_dir"

  require_cmd curl
  require_cmd cao-server
  require_cmd cao-control-panel

  ensure_openclaw_gateway "$gateway_pid_file" "$gateway_log_file"

  start_service \
    "cao-server" \
    "$server_pid_file" \
    "$server_log_file" \
    env SERVER_HOST="$SERVER_HOST" SERVER_PORT="$SERVER_PORT" cao-server

  wait_for_health "cao-server" "http://$SERVER_HOST:$SERVER_PORT/health"

  start_service \
    "cao-control-panel" \
    "$panel_pid_file" \
    "$panel_log_file" \
    env CONTROL_PANEL_HOST="$CONTROL_PANEL_HOST" CONTROL_PANEL_PORT="$CONTROL_PANEL_PORT" CAO_SERVER_URL="$CAO_SERVER_URL" CAO_CONSOLE_PASSWORD="$CAO_CONSOLE_PASSWORD" cao-control-panel

  wait_for_health "cao-control-panel" "http://$CONTROL_PANEL_HOST:$CONTROL_PANEL_PORT/health"

  info "全部服务已启动。"
  echo
  echo "访问地址:"
  echo "- 控制面板: http://$CONTROL_PANEL_HOST:$CONTROL_PANEL_PORT"
  echo "- 后端健康检查: http://$SERVER_HOST:$SERVER_PORT/health"
  echo
  echo "日志文件:"
  echo "- $gateway_log_file"
  echo "- $server_log_file"
  echo "- $panel_log_file"
  echo
  echo "PID 文件:"
  echo "- $gateway_pid_file"
  echo "- $server_pid_file"
  echo "- $panel_pid_file"
}

main "$@"

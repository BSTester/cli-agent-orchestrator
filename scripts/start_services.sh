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

mkdir -p "$LOG_DIR" "$PID_DIR"

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
  cd "$ROOT_DIR"

  require_cmd curl
  require_cmd cao-server
  require_cmd cao-control-panel

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

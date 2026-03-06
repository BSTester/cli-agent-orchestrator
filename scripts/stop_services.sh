#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME_DIR="$ROOT_DIR/.runtime"
PID_DIR="$RUNTIME_DIR/pids"

SERVER_PID_FILE="$PID_DIR/cao-server.pid"
PANEL_PID_FILE="$PID_DIR/cao-control-panel.pid"

info() {
  echo "[INFO] $*"
}

warn() {
  echo "[WARN] $*"
}

has_cmd() {
  command -v "$1" >/dev/null 2>&1
}

detect_os() {
  uname -s 2>/dev/null || echo "Unknown"
}

list_pids_by_name() {
  local name="$1"

  if has_cmd pgrep; then
    pgrep -f "$name" || true
    return
  fi

  if ! has_cmd ps || ! has_cmd awk; then
    return
  fi

  local os_name
  os_name="$(detect_os)"

  if [[ "$os_name" == "Darwin" ]]; then
    ps ax -o pid= -o command= | awk -v n="$name" '$0 ~ n && $0 !~ /awk/ {print $1}'
    return
  fi

  ps -eo pid=,args= | awk -v n="$name" '$0 ~ n && $0 !~ /awk/ {print $1}'
}

wait_for_exit() {
  local pid="$1"
  local retries="${2:-20}"
  local sleep_seconds="${3:-0.2}"

  for ((i = 1; i <= retries; i++)); do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$sleep_seconds"
  done

  return 1
}

stop_by_pid_file() {
  local name="$1"
  local pid_file="$2"

  if [[ ! -f "$pid_file" ]]; then
    warn "$name 未找到 PID 文件: $pid_file"
    return 1
  fi

  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [[ -z "$pid" ]]; then
    warn "$name PID 文件为空，已移除: $pid_file"
    rm -f "$pid_file"
    return 1
  fi

  if ! kill -0 "$pid" >/dev/null 2>&1; then
    warn "$name 进程不存在 (pid=$pid)，清理 PID 文件"
    rm -f "$pid_file"
    return 1
  fi

  info "停止 $name (pid=$pid) ..."
  kill "$pid" >/dev/null 2>&1 || true

  if wait_for_exit "$pid"; then
    info "$name 已停止"
    rm -f "$pid_file"
    return 0
  fi

  warn "$name 未在预期时间退出，发送 SIGKILL"
  kill -9 "$pid" >/dev/null 2>&1 || true

  if wait_for_exit "$pid" 10 0.2; then
    info "$name 已强制停止"
  else
    warn "$name 可能仍在运行，请手动检查 pid=$pid"
  fi

  rm -f "$pid_file"
  return 0
}

stop_by_name_fallback() {
  local name="$1"
  local pids
  pids="$(list_pids_by_name "$name" || true)"
  if [[ -z "$pids" ]]; then
    return
  fi

  warn "检测到残留进程，按名称停止: $name ($pids)"
  while IFS= read -r pid; do
    if [[ -n "$pid" ]]; then
      kill "$pid" >/dev/null 2>&1 || true
    fi
  done <<<"$pids"
}

main() {
  local any_stopped=0

  if stop_by_pid_file "cao-server" "$SERVER_PID_FILE"; then
    any_stopped=1
  fi

  if stop_by_pid_file "cao-control-panel" "$PANEL_PID_FILE"; then
    any_stopped=1
  fi

  stop_by_name_fallback "cao-server"
  stop_by_name_fallback "cao-control-panel"

  if [[ "$any_stopped" -eq 0 ]]; then
    warn "未通过 PID 文件发现运行中的服务，已执行进程名兜底清理。"
  else
    info "服务停止流程完成。"
  fi
}

main "$@"

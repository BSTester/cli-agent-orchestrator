#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CAO_VERIFY_AGENT_CLIS_ON_START="${CAO_VERIFY_AGENT_CLIS_ON_START:-1}"
RUNTIME_DIR="${CAO_RUNTIME_DIR:-${HOME:-/home/cao}/.local/state/cli-agent-orchestrator/runtime}"
RUNTIME_LOG_DIR="$RUNTIME_DIR/logs"

mkdir -p "$RUNTIME_LOG_DIR"
# Keep these filenames aligned with scripts/start_services.sh, which writes logs
# under $CAO_RUNTIME_DIR/logs when the Docker image runs script-only bootstraps.
touch "$RUNTIME_LOG_DIR/openclaw-gateway.log" "$RUNTIME_LOG_DIR/cao-server.log" "$RUNTIME_LOG_DIR/cao-control-panel.log"

ensure_runtime_provider_clis() {
	if [[ "$CAO_VERIFY_AGENT_CLIS_ON_START" != "1" ]]; then
		echo "[INFO] 已跳过 provider CLI 启动校验（CAO_VERIFY_AGENT_CLIS_ON_START=$CAO_VERIFY_AGENT_CLIS_ON_START）。"
		return
	fi

	echo "[INFO] 启动前校验 7 个 provider CLI，缺失项将按需补装。"
	# shellcheck source=/dev/null
	source "$SCRIPT_DIR/install_services.sh"
	install_missing_agent_clis
}

ensure_runtime_provider_clis

if [[ "${CAO_RUNTIME_INSTALL:-0}" == "1" ]]; then
	echo "[INFO] 已启用运行时安装模式：先安装再启动服务。"
	bash "$SCRIPT_DIR/install_and_start_services.sh" "$@"
else
	echo "[INFO] 使用镜像内预装依赖，直接启动服务。"
	bash "$SCRIPT_DIR/start_services.sh" "$@"
fi

exec tail -F "$RUNTIME_LOG_DIR/openclaw-gateway.log" "$RUNTIME_LOG_DIR/cao-server.log" "$RUNTIME_LOG_DIR/cao-control-panel.log"

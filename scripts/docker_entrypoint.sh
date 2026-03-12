#!/usr/bin/env bash
set -euo pipefail

RUNTIME_DIR="${CAO_RUNTIME_DIR:-${HOME:-/home/cao}/.local/state/cli-agent-orchestrator/runtime}"
RUNTIME_LOG_DIR="$RUNTIME_DIR/logs"

mkdir -p "$RUNTIME_LOG_DIR"
# Keep these filenames aligned with scripts/start_services.sh, which writes logs
# under $CAO_RUNTIME_DIR/logs when the Docker image runs script-only bootstraps.
touch "$RUNTIME_LOG_DIR/cao-server.log" "$RUNTIME_LOG_DIR/cao-control-panel.log"

if [[ "${CAO_RUNTIME_INSTALL:-0}" == "1" ]]; then
	echo "[INFO] 已启用运行时安装模式：先安装再启动服务。"
	bash /opt/cao/scripts/install_and_start_services.sh "$@"
else
	echo "[INFO] 使用镜像内预装依赖，直接启动服务。"
	bash /opt/cao/scripts/start_services.sh "$@"
fi

exec tail -F "$RUNTIME_LOG_DIR/cao-server.log" "$RUNTIME_LOG_DIR/cao-control-panel.log"

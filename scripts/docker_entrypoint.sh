#!/usr/bin/env bash
set -euo pipefail

RUNTIME_LOG_DIR="/opt/cao/.runtime/logs"

bash /opt/cao/scripts/install_and_start_services.sh "$@"

mkdir -p "$RUNTIME_LOG_DIR"
touch "$RUNTIME_LOG_DIR/cao-server.log" "$RUNTIME_LOG_DIR/cao-control-panel.log"

exec tail -F "$RUNTIME_LOG_DIR/cao-server.log" "$RUNTIME_LOG_DIR/cao-control-panel.log"

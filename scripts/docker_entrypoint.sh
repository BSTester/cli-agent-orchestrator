#!/usr/bin/env bash
set -euo pipefail

RUNTIME_LOG_DIR="/opt/cao/.runtime/logs"

mkdir -p "$RUNTIME_LOG_DIR"
# Keep these filenames aligned with scripts/start_services.sh, which writes logs
# under /opt/cao/.runtime/logs when the Docker image runs script-only bootstraps.
touch "$RUNTIME_LOG_DIR/cao-server.log" "$RUNTIME_LOG_DIR/cao-control-panel.log"

bash /opt/cao/scripts/install_and_start_services.sh "$@"

exec tail -F "$RUNTIME_LOG_DIR/cao-server.log" "$RUNTIME_LOG_DIR/cao-control-panel.log"

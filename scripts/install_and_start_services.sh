#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

info() {
  echo "[INFO] $*"
}

main() {
  info "兼容模式：先执行安装脚本，再执行启动脚本。"
  bash "$ROOT_DIR/scripts/install_services.sh" "$@"
  bash "$ROOT_DIR/scripts/start_services.sh" "$@"
}

main "$@"

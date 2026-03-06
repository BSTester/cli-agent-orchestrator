#!/usr/bin/env bash
set -euo pipefail

info() {
  echo "[INFO] $*"
}

main() {
  local root_dir
  if [[ -n "${BASH_SOURCE[0]-}" && "${BASH_SOURCE[0]}" != "bash" ]]; then
    root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  else
    root_dir="$(pwd)"
  fi

  info "兼容模式：先执行安装脚本，再执行启动脚本。"
  bash "$root_dir/scripts/install_services.sh" "$@"
  bash "$root_dir/scripts/start_services.sh" "$@"
}

main "$@"

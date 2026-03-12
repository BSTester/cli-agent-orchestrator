#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DOCKER_INIT_ROOT="${DOCKER_INIT_ROOT:-$REPO_ROOT/.docker}"
DOCKER_INIT_IMAGE="${DOCKER_INIT_IMAGE:-cao-dashboard}"
CONTAINER_HOME="${CONTAINER_HOME:-/home/cao}"
BIND_MOUNT_PATHS=(
	".aws:aws"
	".claude:claude"
	".codex:codex"
	".openclaw:openclaw"
	".kiro:kiro"
	".qoder:qoder"
	".copilot:copilot"
	".codebuddy:codebuddy"
	"workspace:workspace"
)
INIT_CONTAINER_ID=""

info() {
	echo "[INFO] $*"
}

warn() {
	echo "[WARN] $*" >&2
}

die() {
	echo "[ERROR] $*" >&2
	exit 1
}

require_cmd() {
	command -v "$1" >/dev/null 2>&1 || die "缺少命令: $1"
}

is_empty_dir() {
	local dir="$1"
	[[ ! -d "$dir" ]] && return 0
	[[ -z "$(find "$dir" -mindepth 1 -print -quit 2>/dev/null)" ]]
}

copy_path_from_container() {
	local container_id="$1"
	local container_relative_path="$2"
	local host_relative_path="$3"
	local src="$container_id:$CONTAINER_HOME/$container_relative_path/."
	local dest="$DOCKER_INIT_ROOT/$host_relative_path"

	mkdir -p "$dest"

	if ! is_empty_dir "$dest"; then
		info "跳过非空目录：$dest"
		return
	fi

	info "初始化目录：$dest <- $CONTAINER_HOME/$container_relative_path"
	if ! docker cp "$src" "$dest/"; then
		warn "复制失败，跳过：$CONTAINER_HOME/$container_relative_path"
	fi
}

initialize_bind_mounts() {
	require_cmd docker
	mkdir -p "$DOCKER_INIT_ROOT"

	if ! docker image inspect "$DOCKER_INIT_IMAGE" >/dev/null 2>&1; then
		die "未找到镜像 $DOCKER_INIT_IMAGE，请先执行: docker compose build"
	fi

	INIT_CONTAINER_ID="$(docker create "$DOCKER_INIT_IMAGE" true)"
	trap 'if [[ -n "$INIT_CONTAINER_ID" ]]; then docker rm -f "$INIT_CONTAINER_ID" >/dev/null 2>&1 || true; fi' EXIT

	local entry container_relative_path host_relative_path
	for entry in "${BIND_MOUNT_PATHS[@]}"; do
		container_relative_path="${entry%%:*}"
		host_relative_path="${entry##*:}"
		copy_path_from_container "$INIT_CONTAINER_ID" "$container_relative_path" "$host_relative_path"
	done

	info "宿主机挂载目录初始化完成。"
}

initialize_bind_mounts
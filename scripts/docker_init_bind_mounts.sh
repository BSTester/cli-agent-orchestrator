#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DOCKER_INIT_IMAGE="${DOCKER_INIT_IMAGE:-cao-dashboard}"
CONTAINER_HOME="${CONTAINER_HOME:-/home/cao}"
DOCKER_SERVICE_NAME="${DOCKER_SERVICE_NAME:-cao}"
DISCOVERY_COMPOSE_PROJECT="cao-bind-init-$$"
BIND_MOUNT_PATHS=()
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

cleanup() {
	if [[ -n "$INIT_CONTAINER_ID" ]]; then
		docker rm -f "$INIT_CONTAINER_ID" >/dev/null 2>&1 || true
	fi
	docker compose -p "$DISCOVERY_COMPOSE_PROJECT" rm -fsv "$DOCKER_SERVICE_NAME" >/dev/null 2>&1 || true
}

is_empty_dir() {
	local dir="$1"
	[[ ! -d "$dir" ]] && return 0
	[[ -z "$(find "$dir" -mindepth 1 -print -quit 2>/dev/null)" ]]
}

copy_path_from_container() {
	local container_id="$1"
	local container_relative_path="$2"
	local host_path="$3"
	local src="$container_id:$CONTAINER_HOME/$container_relative_path/."
	local dest="$host_path"

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

discover_bind_mount_paths() {
	require_cmd docker

	if ! docker compose version >/dev/null 2>&1; then
		die "当前 Docker 环境不支持 'docker compose'，无法自动识别宿主机挂载路径。"
	fi

	info "解析 docker compose 中服务 $DOCKER_SERVICE_NAME 的 bind 挂载配置"
	if ! docker compose -p "$DISCOVERY_COMPOSE_PROJECT" create "$DOCKER_SERVICE_NAME" >/dev/null; then
		die "无法创建用于探测挂载配置的临时 compose 容器，请检查 docker-compose 配置和服务名。"
	fi

	local discovery_container_id
	discovery_container_id="$(docker compose -p "$DISCOVERY_COMPOSE_PROJECT" ps -aq "$DOCKER_SERVICE_NAME" | head -n 1)"
	[[ -n "$discovery_container_id" ]] || die "未找到 compose 服务 $DOCKER_SERVICE_NAME 的临时容器。"

	local mount_type mount_source mount_target container_relative_path
	while IFS=$'\t' read -r mount_type mount_source mount_target; do
		[[ "$mount_type" == "bind" ]] || continue

		case "$mount_target" in
			"$CONTAINER_HOME")
				container_relative_path="."
				;;
			"$CONTAINER_HOME"/*)
				container_relative_path="${mount_target#"$CONTAINER_HOME/"}"
				;;
			*)
				continue
				;;
		esac

		BIND_MOUNT_PATHS+=("$container_relative_path:$mount_source")
		info "发现挂载：$mount_source -> $mount_target"
	done < <(docker inspect --format '{{range .Mounts}}{{printf "%s\t%s\t%s\n" .Type .Source .Destination}}{{end}}' "$discovery_container_id")

	if [[ ${#BIND_MOUNT_PATHS[@]} -eq 0 ]]; then
		die "未发现任何映射到 $CONTAINER_HOME 下的 bind 挂载。"
	fi
}

initialize_bind_mounts() {
	require_cmd docker
	trap cleanup EXIT

	if ! docker image inspect "$DOCKER_INIT_IMAGE" >/dev/null 2>&1; then
		die "未找到镜像 $DOCKER_INIT_IMAGE，请先执行: docker compose build"
	fi

	discover_bind_mount_paths

	INIT_CONTAINER_ID="$(docker create "$DOCKER_INIT_IMAGE" true)"

	local entry container_relative_path host_path
	for entry in "${BIND_MOUNT_PATHS[@]}"; do
		container_relative_path="${entry%%:*}"
		host_path="${entry#*:}"
		copy_path_from_container "$INIT_CONTAINER_ID" "$container_relative_path" "$host_path"
	done

	info "宿主机挂载目录初始化完成。"
}

initialize_bind_mounts
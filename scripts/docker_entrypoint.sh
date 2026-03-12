#!/usr/bin/env bash
set -euo pipefail

HOME_TEMPLATE_DIR="/opt/cao/home-template"
RUNTIME_DIR="${CAO_RUNTIME_DIR:-${HOME:-/home/cao}/.local/state/cli-agent-orchestrator/runtime}"
RUNTIME_LOG_DIR="$RUNTIME_DIR/logs"
PERSISTENT_HOME_DIRS=(
	".aws/cli-agent-orchestrator"
	".aws/amazonq"
	".claude"
	".codex"
	".openclaw"
	".kiro"
	".qoder"
	".copilot"
	".codebuddy"
)

seed_persistent_home_dirs() {
	if [[ -z "${HOME:-}" ]]; then
		echo "[WARN] HOME 未设置，跳过 home 配置目录初始化。"
		return
	fi

	mkdir -p "$HOME"

	if [[ ! -d "$HOME_TEMPLATE_DIR" ]]; then
		return
	fi

	local relative_path
	for relative_path in "${PERSISTENT_HOME_DIRS[@]}"; do
		local src="$HOME_TEMPLATE_DIR/$relative_path"
		local dest="$HOME/$relative_path"

		if [[ ! -d "$src" ]]; then
			continue
		fi

		mkdir -p "$dest"

		if [[ -n "$(find "$dest" -mindepth 1 -print -quit 2>/dev/null)" ]]; then
			continue
		fi

		echo "[INFO] 初始化 home 配置目录：$dest"
		cp -a "$src/." "$dest/"
	done
}

repair_cli_from_template() {
	local command_name="$1"
	shift

	if command -v "$command_name" >/dev/null 2>&1; then
		return
	fi

	echo "[WARN] 检测到 $command_name 不可用，尝试从镜像模板修复。"

	local relative_path
	for relative_path in "$@"; do
		local src="$HOME_TEMPLATE_DIR/$relative_path"
		local dest="$HOME/$relative_path"

		if [[ ! -e "$src" && ! -L "$src" ]]; then
			continue
		fi

		rm -rf "$dest"
		mkdir -p "$(dirname "$dest")"
		cp -a "$src" "$dest"
	done

	hash -r 2>/dev/null || true
}

seed_persistent_home_dirs
repair_cli_from_template "claude" ".local/bin/claude" ".local/lib/node_modules/@anthropic-ai"
repair_cli_from_template "codex" ".local/bin/codex" ".local/lib/node_modules/@openai"
repair_cli_from_template "copilot" ".local/bin/copilot" ".local/lib/node_modules/@github"
repair_cli_from_template "codebuddy" ".local/bin/codebuddy" ".local/lib/node_modules/@tencent-ai"
repair_cli_from_template "openclaw" ".local/bin/openclaw" ".local/lib/node_modules/openclaw"
repair_cli_from_template "qodercli" ".local/bin/qodercli" ".qoder"
repair_cli_from_template "kiro-cli" ".local/bin/kiro-cli" ".local/bin/kiro-cli-chat" ".local/bin/kiro-cli-term"

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

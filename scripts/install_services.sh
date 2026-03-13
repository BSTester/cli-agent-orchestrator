#!/usr/bin/env bash
set -euo pipefail

CAO_REPO_REF="${CAO_REPO_REF:-main}"
CAO_REPO_URL="${CAO_REPO_URL:-https://github.com/BSTester/cli-agent-orchestrator.git}"
CAO_TOOL_SPEC="${CAO_TOOL_SPEC:-git+${CAO_REPO_URL}@${CAO_REPO_REF}}"
OPENCLAW_INSTALL_METHOD="${OPENCLAW_INSTALL_METHOD:-npm}"
OPENCLAW_NO_PROMPT="${OPENCLAW_NO_PROMPT:-1}"
OPENCLAW_NO_ONBOARD="${OPENCLAW_NO_ONBOARD:-1}"
OPENCLAW_NPM_LOGLEVEL="${OPENCLAW_NPM_LOGLEVEL:-error}"
SHARP_IGNORE_GLOBAL_LIBVIPS="${SHARP_IGNORE_GLOBAL_LIBVIPS:-1}"
OPENCLAW_CAO_PLUGIN_ENABLE="${OPENCLAW_CAO_PLUGIN_ENABLE:-1}"
OPENCLAW_CAO_PLUGIN_ID="${OPENCLAW_CAO_PLUGIN_ID:-cao-tools}"
CAO_SKIP_TOOL_INSTALL="${CAO_SKIP_TOOL_INSTALL:-0}"
NPM_CONFIG_PREFIX="${NPM_CONFIG_PREFIX:-$HOME/.local}"

# Skills discovery integration
SKILLS_DISCOVERY_SPEC="${SKILLS_DISCOVERY_SPEC:-@Kamalnrf/claude-plugins/skills-discovery}"
SKILLS_INSTALLER_CMD="${SKILLS_INSTALLER_CMD:-skills-installer}"
# Test contract marker: test/scripts/test_install_services_script.py reads bootstrap lines until here.
# INSTALLER_BOOTSTRAP_END

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

print_manual_install_command() {
  local component="$1"
  local cmd="$2"
  warn "${component} 自动安装失败，请手动执行：${cmd}"
}

require_cmd() {
  local cmd="$1"
  command -v "$cmd" >/dev/null 2>&1 || die "缺少命令: $cmd"
}

has_cmd() {
  command -v "$1" >/dev/null 2>&1
}

run_privileged() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
    return
  fi

  if has_cmd sudo; then
    sudo "$@"
    return
  fi

  die "需要管理员权限执行: $*（请安装 sudo 或使用 root 运行）"
}

detect_linux_package_manager() {
  if has_cmd apt-get; then
    echo "apt-get"
    return
  fi

  if has_cmd dnf; then
    echo "dnf"
    return
  fi

  if has_cmd yum; then
    echo "yum"
    return
  fi

  if has_cmd zypper; then
    echo "zypper"
    return
  fi

  if has_cmd pacman; then
    echo "pacman"
    return
  fi

  if has_cmd apk; then
    echo "apk"
    return
  fi

  die "无法识别 Linux 包管理器，请手动安装: $*"
}

install_packages_linux() {
  local packages=("$@")
  local pkg_manager
  pkg_manager="$(detect_linux_package_manager)"

  if [[ "$pkg_manager" == "apt-get" ]]; then
    run_privileged apt-get update
    run_privileged apt-get install -y "${packages[@]}"
    return
  fi

  if [[ "$pkg_manager" == "dnf" ]]; then
    run_privileged dnf install -y "${packages[@]}"
    return
  fi

  if [[ "$pkg_manager" == "yum" ]]; then
    run_privileged yum install -y "${packages[@]}"
    return
  fi

  if [[ "$pkg_manager" == "zypper" ]]; then
    run_privileged zypper --non-interactive install "${packages[@]}"
    return
  fi

  if [[ "$pkg_manager" == "pacman" ]]; then
    run_privileged pacman -Sy --noconfirm "${packages[@]}"
    return
  fi

  if [[ "$pkg_manager" == "apk" ]]; then
    run_privileged apk add --no-cache "${packages[@]}"
    return
  fi
}

install_packages_macos() {
  local packages=("$@")
  if ! has_cmd brew; then
    die "macOS 下未检测到 Homebrew，请先安装 brew 后重试。"
  fi
  brew update
  brew install "${packages[@]}"
}

ensure_basic_tools() {
  local missing=()
  for cmd in curl git; do
    if ! has_cmd "$cmd"; then
      missing+=("$cmd")
    fi
  done

  if [[ "${#missing[@]}" -eq 0 ]]; then
    return
  fi

  info "检测到缺少基础命令: ${missing[*]}，尝试自动安装..."
  case "$(uname -s)" in
    Darwin)
      install_packages_macos "${missing[@]}"
      ;;
    Linux)
      install_packages_linux "${missing[@]}"
      ;;
    *)
      die "当前系统不支持自动安装基础命令，请手动安装: ${missing[*]}"
      ;;
  esac
}

ensure_python3() {
  local linux_pkg_manager=""

  if has_cmd python3; then
    return
  fi

  info "未检测到 python3，尝试自动安装..."
  case "$(uname -s)" in
    Darwin)
      install_packages_macos python
      ;;
    Linux)
      linux_pkg_manager="$(detect_linux_package_manager)"
      if [[ "$linux_pkg_manager" == "apt-get" ]]; then
        install_packages_linux python3 python3-venv
      else
        install_packages_linux python3
      fi
      ;;
    *)
      die "当前系统不支持自动安装 Python3，请手动安装 Python 3.10+"
      ;;
  esac
}

ensure_nodejs() {
  if has_cmd node && has_cmd npm && has_cmd npx; then
    return
  fi

  info "未检测到 Node.js/npm，尝试自动安装..."
  case "$(uname -s)" in
    Darwin)
      install_packages_macos node
      ;;
    Linux)
      install_packages_linux nodejs npm
      ;;
    *)
      die "当前系统不支持自动安装 Node.js，请手动安装 Node.js 18+"
      ;;
  esac

  has_cmd node || die "Node.js 安装失败，请手动安装后重试。"
  has_cmd npm || die "npm 安装失败，请手动安装后重试。"
  has_cmd npx || die "npx 不可用，请手动安装后重试。"
}

ensure_uv() {
  if has_cmd uv; then
    return
  fi

  info "未检测到 uv，正在安装..."
  require_cmd curl
  if ! curl -LsSf https://astral.sh/uv/install.sh | sh; then
    print_manual_install_command "uv" "curl -LsSf https://astral.sh/uv/install.sh | sh"
    die "uv 自动安装失败。"
  fi

  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  if ! has_cmd uv; then
    print_manual_install_command "uv" "source ~/.bashrc 或 source ~/.zshrc 后重试，或重新执行：curl -LsSf https://astral.sh/uv/install.sh | sh"
    die "uv 安装完成但当前 shell 未找到 uv。"
  fi
}

ensure_tmux() {
  if has_cmd tmux; then
    return
  fi

  info "未检测到 tmux，尝试自动安装..."
  case "$(uname -s)" in
    Darwin)
      install_packages_macos tmux
      ;;
    Linux)
      install_packages_linux tmux
      ;;
    *)
      die "未检测到 tmux，且当前系统不支持自动安装，请手动安装 tmux 3.2+"
      ;;
  esac

  has_cmd tmux || die "tmux 安装失败，请手动安装后重试。"
}

ensure_tool_path() {
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$(npm config get prefix 2>/dev/null || echo "$HOME/.npm-global")/bin:$PATH"
}

ensure_npm_global_prefix() {
  mkdir -p "$NPM_CONFIG_PREFIX/bin"
  export NPM_CONFIG_PREFIX
  ensure_tool_path
}

install_npm_global_package() {
  local command_name="$1"
  local package_name="$2"
  local manual_cmd="npm install -g $package_name"

  if has_cmd "$command_name"; then
    info "$command_name 已安装，跳过。"
    return
  fi

  ensure_npm_global_prefix
  info "安装 $command_name（npm 全局包: $package_name）..."
  if ! npm install -g "$package_name"; then
    print_manual_install_command "$command_name" "$manual_cmd"
    return
  fi

  ensure_tool_path
  if ! has_cmd "$command_name"; then
    print_manual_install_command "$command_name" "$manual_cmd"
  fi
}

openclaw_config_path() {
  echo "${OPENCLAW_CONFIG_PATH:-$HOME/.openclaw/openclaw.json}"
}

openclaw_plugin_source_dir() {
  local root_dir
  root_dir="$(pwd)"
  echo "$root_dir/extensions/openclaw-cao-tools"
}

build_openclaw_install_cmd() {
  printf \
    'env OPENCLAW_INSTALL_METHOD=%q OPENCLAW_NO_PROMPT=%q OPENCLAW_NO_ONBOARD=%q OPENCLAW_NPM_LOGLEVEL=%q SHARP_IGNORE_GLOBAL_LIBVIPS=%q npm install -g openclaw@latest' \
    "$OPENCLAW_INSTALL_METHOD" \
    "$OPENCLAW_NO_PROMPT" \
    "$OPENCLAW_NO_ONBOARD" \
    "$OPENCLAW_NPM_LOGLEVEL" \
    "$SHARP_IGNORE_GLOBAL_LIBVIPS"
}

provider_cli_command() {
  local provider_id="$1"
  case "$provider_id" in
    claude_code)
      echo "claude"
      ;;
    codex)
      echo "codex"
      ;;
    codebuddy)
      echo "codebuddy"
      ;;
    kiro_cli)
      echo "kiro-cli"
      ;;
    qoder_cli)
      echo "qodercli"
      ;;
    copilot)
      echo "copilot"
      ;;
    openclaw)
      echo "openclaw"
      ;;
    *)
      return 1
      ;;
  esac
}

install_provider_cli() {
  local provider_id="$1"

  case "$provider_id" in
    claude_code)
      install_npm_global_package "claude" "@anthropic-ai/claude-code"
      ;;
    codex)
      install_npm_global_package "codex" "@openai/codex"
      ;;
    codebuddy)
      install_npm_global_package "codebuddy" "@tencent-ai/codebuddy-code"
      ;;
    kiro_cli)
      if has_cmd kiro-cli; then
        info "kiro-cli 已安装，跳过。"
      else
        info "安装 kiro-cli（官方方式）..."
        if ! curl -fsSL https://cli.kiro.dev/install | bash; then
          print_manual_install_command "kiro-cli" "curl -fsSL https://cli.kiro.dev/install | bash"
        fi
        ensure_tool_path
        if ! has_cmd kiro-cli; then
          print_manual_install_command "kiro-cli" "curl -fsSL https://cli.kiro.dev/install | bash"
        fi
      fi
      ;;
    qoder_cli)
      if has_cmd qodercli; then
        info "qodercli 已安装，跳过。"
      else
        info "安装 qodercli（官方方式）..."
        if ! curl -fsSL https://qoder.com/install | bash; then
          print_manual_install_command "qodercli" "curl -fsSL https://qoder.com/install | bash"
        fi
        ensure_tool_path
        if ! has_cmd qodercli; then
          print_manual_install_command "qodercli" "curl -fsSL https://qoder.com/install | bash"
        fi
      fi
      ;;
    copilot)
      install_npm_global_package "copilot" "@github/copilot"
      ;;
    openclaw)
      if has_cmd openclaw; then
        info "openclaw 已安装，跳过。"
      else
        local openclaw_install_cmd="${OPENCLAW_INSTALL_CMD:-$(build_openclaw_install_cmd)}"
        info "安装 openclaw（静默模式，跳过引导配置）..."
        if ! bash -lc "$openclaw_install_cmd"; then
          print_manual_install_command "openclaw" "$openclaw_install_cmd"
        fi
        ensure_tool_path
        if ! has_cmd openclaw; then
          print_manual_install_command "openclaw" "$openclaw_install_cmd"
        fi
      fi
      ;;
    *)
      die "不支持的 provider CLI: $provider_id"
      ;;
  esac
}

install_missing_agent_clis() {
  local providers=(claude_code codex codebuddy kiro_cli qoder_cli copilot openclaw)
  local missing_providers=()
  local provider_id=""
  local command_name=""

  ensure_nodejs
  ensure_npm_global_prefix
  ensure_tool_path

  for provider_id in "${providers[@]}"; do
    command_name="$(provider_cli_command "$provider_id")" || continue
    if ! has_cmd "$command_name"; then
      missing_providers+=("$provider_id")
    fi
  done

  if [[ ${#missing_providers[@]} -eq 0 ]]; then
    info "7 个 provider CLI 已全部安装，无需补装。"
    return
  fi

  info "检测到缺失 provider CLI：${missing_providers[*]}"
  for provider_id in "${missing_providers[@]}"; do
    install_provider_cli "$provider_id"
  done
}

install_agent_clis() {
  local providers=(claude_code codex codebuddy kiro_cli qoder_cli copilot openclaw)
  local provider_id=""

  for provider_id in "${providers[@]}"; do
    install_provider_cli "$provider_id"
  done
}

merge_openclaw_plugin_config() {
  local config_path="$1"

  node - "$config_path" "$OPENCLAW_CAO_PLUGIN_ID" <<'NODE'
const fs = require("node:fs");
const path = require("node:path");

const configPath = process.argv[2];
const pluginId = process.argv[3];

const defaultConfig = {
  plugins: {
    enabled: true,
    entries: {
      [pluginId]: {
        enabled: true,
        config: {
          baseUrl: process.env.CAO_SERVER_URL || "http://localhost:9889",
          defaultProvider: "openclaw",
        },
      },
    },
  },
  tools: {
    allow: ["group:openclaw", "group:plugins", "cao_handoff", "cao_assign", "cao_send_message"],
  },
};

function ensureObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

let cfg = {};
if (fs.existsSync(configPath)) {
  const raw = fs.readFileSync(configPath, "utf8").trim();
  if (raw.length > 0) {
    try {
      cfg = JSON.parse(raw);
    } catch (err) {
      process.stderr.write(
        `OPENCLAW_CONFIG_PARSE_ERROR:${configPath}: ${String(err && err.message ? err.message : err)}\n`,
      );
      process.exit(2);
    }
  }
}

cfg = ensureObject(cfg);
cfg.plugins = ensureObject(cfg.plugins);
cfg.plugins.enabled = true;
cfg.plugins.entries = ensureObject(cfg.plugins.entries);

const currentEntry = ensureObject(cfg.plugins.entries[pluginId]);
const currentPluginConfig = ensureObject(currentEntry.config);
cfg.plugins.entries[pluginId] = {
  ...currentEntry,
  enabled: true,
  config: {
    baseUrl: currentPluginConfig.baseUrl || defaultConfig.plugins.entries[pluginId].config.baseUrl,
    defaultProvider:
      currentPluginConfig.defaultProvider ||
      defaultConfig.plugins.entries[pluginId].config.defaultProvider,
    ...currentPluginConfig,
  },
};

cfg.tools = ensureObject(cfg.tools);
const allow = Array.isArray(cfg.tools.allow) ? cfg.tools.allow.map(String) : [];
const requiredAllow = defaultConfig.tools.allow;
for (const item of requiredAllow) {
  if (!allow.includes(item)) {
    allow.push(item);
  }
}
cfg.tools.allow = allow;

const dir = path.dirname(configPath);
fs.mkdirSync(dir, { recursive: true });
fs.writeFileSync(configPath, `${JSON.stringify(cfg, null, 2)}\n`, "utf8");
NODE
}

install_openclaw_cao_plugin() {
  if [[ "$OPENCLAW_CAO_PLUGIN_ENABLE" != "1" ]]; then
    info "已跳过 OpenClaw CAO 插件安装（OPENCLAW_CAO_PLUGIN_ENABLE=$OPENCLAW_CAO_PLUGIN_ENABLE）。"
    return
  fi

  if ! has_cmd openclaw; then
    warn "未检测到 openclaw，跳过 CAO 插件安装。"
    return
  fi

  local plugin_source_dir
  plugin_source_dir="$(openclaw_plugin_source_dir)"
  if [[ ! -d "$plugin_source_dir" ]]; then
    warn "未找到 OpenClaw 插件目录，跳过: $plugin_source_dir"
    return
  fi

  # OpenClaw blocks plugin candidates from world-writable paths (common in
  # mounted Windows/WSL workspaces like /mnt/* with mode 777). Stage a safe
  # local copy under ~/.openclaw/extensions before installing in link mode.
  local staged_plugin_dir
  staged_plugin_dir="$HOME/.openclaw/extensions/${OPENCLAW_CAO_PLUGIN_ID}-local"
  mkdir -p "$staged_plugin_dir"
  cp -f "$plugin_source_dir/index.js" "$staged_plugin_dir/index.js"
  cp -f "$plugin_source_dir/openclaw.plugin.json" "$staged_plugin_dir/openclaw.plugin.json"
  if [[ -f "$plugin_source_dir/package.json" ]]; then
    cp -f "$plugin_source_dir/package.json" "$staged_plugin_dir/package.json"
  fi
  chmod 755 "$staged_plugin_dir"
  chmod 644 "$staged_plugin_dir/index.js" "$staged_plugin_dir/openclaw.plugin.json"
  if [[ -f "$staged_plugin_dir/package.json" ]]; then
    chmod 644 "$staged_plugin_dir/package.json"
  fi

  info "安装 OpenClaw CAO 插件（link 模式）: $staged_plugin_dir"
  if ! openclaw plugins install -l "$staged_plugin_dir"; then
    print_manual_install_command "OpenClaw CAO 插件" "openclaw plugins install -l \"$staged_plugin_dir\""
    warn "OpenClaw CAO 插件安装失败，后续配置步骤跳过。"
    return
  fi

  local config_path
  config_path="$(openclaw_config_path)"
  info "写入 OpenClaw 配置（启用 $OPENCLAW_CAO_PLUGIN_ID + 工具 allowlist）: $config_path"
  if ! merge_openclaw_plugin_config "$config_path"; then
    print_manual_install_command "OpenClaw 配置合并" "请手工在 $(openclaw_config_path) 中启用插件 '$OPENCLAW_CAO_PLUGIN_ID' 并将 tools.allow 加入 cao_handoff/cao_assign/cao_send_message"
    warn "OpenClaw 配置自动合并失败，可能是现有配置为 JSON5（含注释/尾逗号）导致。"
    return
  fi

  info "OpenClaw CAO 插件安装并配置完成。"
}

install_skills_discovery_for_all_agents() {
  ensure_nodejs
  info "安装 skills-discovery 服务（所有支持 skills 的 agent 共用）: $SKILLS_DISCOVERY_SPEC"
  if [[ ! -t 0 || ! -t 1 ]]; then
    warn "当前终端不支持交互式安装 skills-discovery。"
    print_manual_install_command "skills-discovery" "npx -y \"$SKILLS_INSTALLER_CMD\" install \"$SKILLS_DISCOVERY_SPEC\""
    return
  fi
  unset npm_config_init_module NPM_CONFIG_INIT_MODULE
  if ! npx -y "$SKILLS_INSTALLER_CMD" install "$SKILLS_DISCOVERY_SPEC"; then
    print_manual_install_command "skills-discovery" "npx -y \"$SKILLS_INSTALLER_CMD\" install \"$SKILLS_DISCOVERY_SPEC\""
  fi
}

install_cao_tool() {
  if [[ "$CAO_SKIP_TOOL_INSTALL" == "1" ]]; then
    info "已跳过 CLI Agent Orchestrator 工具安装（CAO_SKIP_TOOL_INSTALL=1），直接复用现有命令。"
    if ! has_cmd cao || ! has_cmd cao-server || ! has_cmd cao-control-panel; then
      die "已跳过 CLI Agent Orchestrator 安装，但缺少 cao/cao-server/cao-control-panel 命令。"
    fi
    return
  fi

  info "安装/升级 CLI Agent Orchestrator 工具: $CAO_TOOL_SPEC"
  if ! uv tool install "$CAO_TOOL_SPEC" --upgrade; then
    print_manual_install_command "CLI Agent Orchestrator" "uv tool install \"$CAO_TOOL_SPEC\" --upgrade"
    die "CLI Agent Orchestrator 安装失败。"
  fi
  ensure_tool_path

  if ! has_cmd cao || ! has_cmd cao-server || ! has_cmd cao-control-panel; then
    print_manual_install_command "CLI Agent Orchestrator" "uv tool install \"$CAO_TOOL_SPEC\" --upgrade"
    die "CLI Agent Orchestrator 安装完成但命令不可用。"
  fi
}

install_default_agent_profiles() {
  local profile
  for profile in code_supervisor developer reviewer; do
    info "安装预置 Agent 角色: $profile"
    if ! cao install "$profile"; then
      print_manual_install_command "$profile" "cao install $profile"
      die "预置 Agent 角色安装失败: $profile"
    fi
  done
}

main() {
  require_cmd bash
  if [[ -n "${BASH_SOURCE[0]-}" && "${BASH_SOURCE[0]}" != "bash" ]]; then
    cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  fi

  ensure_basic_tools
  ensure_python3
  ensure_uv
  ensure_nodejs
  ensure_tmux

  install_cao_tool
  install_default_agent_profiles
  install_agent_clis
  install_openclaw_cao_plugin
  install_skills_discovery_for_all_agents

  info "安装流程完成。"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi

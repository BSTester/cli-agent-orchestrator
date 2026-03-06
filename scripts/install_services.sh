#!/usr/bin/env bash
set -euo pipefail

CAO_REPO_REF="${CAO_REPO_REF:-main}"
CAO_REPO_URL="${CAO_REPO_URL:-https://github.com/BSTester/cli-agent-orchestrator.git}"
CAO_TOOL_SPEC="git+${CAO_REPO_URL}@${CAO_REPO_REF}"

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

install_agent_clis() {
  ensure_nodejs
  ensure_tool_path

  if has_cmd codex; then
    info "codex 已安装，跳过。"
  else
    info "安装 codex（官方方式）..."
    if ! npm install -g @openai/codex --force --no-os-check; then
      print_manual_install_command "codex" "npm install -g @openai/codex --force --no-os-check"
    fi
    ensure_tool_path
    if ! has_cmd codex; then
      print_manual_install_command "codex" "npm install -g @openai/codex --force --no-os-check"
    fi
  fi

  if has_cmd claude; then
    info "claude 已安装，跳过。"
  else
    info "安装 claude（官方方式）..."
    if ! curl -fsSL https://claude.ai/install.sh | bash; then
      print_manual_install_command "claude" "curl -fsSL https://claude.ai/install.sh | bash"
    fi
    ensure_tool_path
    if ! has_cmd claude; then
      print_manual_install_command "claude" "curl -fsSL https://claude.ai/install.sh | bash"
    fi
  fi

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

  if has_cmd codebuddy; then
    info "codebuddy 已安装，跳过。"
  else
    info "安装 codebuddy（官方方式）..."
    if ! npm install -g @tencent-ai/codebuddy-code; then
      print_manual_install_command "codebuddy" "npm install -g @tencent-ai/codebuddy-code"
    fi
    ensure_tool_path
    if ! has_cmd codebuddy; then
      print_manual_install_command "codebuddy" "npm install -g @tencent-ai/codebuddy-code"
    fi
  fi

  if has_cmd copilot; then
    info "copilot 已安装，跳过。"
  else
    info "安装 copilot（官方方式）..."
    if ! npm install -g @github/copilot; then
      print_manual_install_command "copilot" "npm install -g @github/copilot"
    fi
    ensure_tool_path
    if ! has_cmd copilot; then
      print_manual_install_command "copilot" "npm install -g @github/copilot"
    fi
  fi
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
  install_skills_discovery_for_all_agents

  info "安装流程完成。"
}

main "$@"

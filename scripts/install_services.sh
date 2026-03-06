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

die() {
  echo "[ERROR] $*" >&2
  exit 1
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
  curl -LsSf https://astral.sh/uv/install.sh | sh

  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  has_cmd uv || die "uv 安装完成但当前 shell 未找到 uv，请手动执行: source ~/.bashrc 或 source ~/.zshrc"
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
    npm install -g @openai/codex --force --no-os-check
    ensure_tool_path
    has_cmd codex || die "codex 安装失败。"
  fi

  if has_cmd claude; then
    info "claude 已安装，跳过。"
  else
    info "安装 claude（官方方式）..."
    curl -fsSL https://claude.ai/install.sh | bash
    ensure_tool_path
    has_cmd claude || die "claude 安装失败。"
  fi

  if has_cmd kiro-cli; then
    info "kiro-cli 已安装，跳过。"
  else
    info "安装 kiro-cli（官方方式）..."
    curl -fsSL https://cli.kiro.dev/install | bash
    ensure_tool_path
    has_cmd kiro-cli || die "kiro-cli 安装失败。"
  fi

  if has_cmd qodercli; then
    info "qodercli 已安装，跳过。"
  else
    info "安装 qodercli（官方方式）..."
    curl -fsSL https://qoder.com/install | bash
    ensure_tool_path
    has_cmd qodercli || die "qodercli 安装失败。"
  fi

  if has_cmd codebuddy; then
    info "codebuddy 已安装，跳过。"
  else
    info "安装 codebuddy（官方方式）..."
    npm install -g @tencent-ai/codebuddy-code
    ensure_tool_path
    has_cmd codebuddy || die "codebuddy 安装失败。"
  fi

  if has_cmd copilot; then
    info "copilot 已安装，跳过。"
  else
    info "安装 copilot（官方方式）..."
    npm install -g @github/copilot
    ensure_tool_path
    has_cmd copilot || die "copilot 安装失败。"
  fi
}

install_skills_discovery_for_all_agents() {
  ensure_nodejs
  info "安装 skills-discovery 服务（所有支持 skills 的 agent 共用）: $SKILLS_DISCOVERY_SPEC"
  npx -y "$SKILLS_INSTALLER_CMD" install "$SKILLS_DISCOVERY_SPEC"
}

install_cao_tool() {
  info "安装/升级 CLI Agent Orchestrator 工具: $CAO_TOOL_SPEC"
  uv tool install "$CAO_TOOL_SPEC" --upgrade
  ensure_tool_path

  require_cmd cao
  require_cmd cao-server
  require_cmd cao-control-panel
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
  install_agent_clis
  install_skills_discovery_for_all_agents

  info "安装流程完成。"
}

main "$@"

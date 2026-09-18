#!/bin/sh
# install.sh — MinimalAgentV2 一键安装脚本
# 用法:
#   curl -fsSL https://your-cdn/install.sh | sh
#   sh -c "$(curl -fsSL https://your-cdn/install.sh)"
#   sh -c "$(curl -fsSL https://your-cdn/install.sh)" -- https://github.com/you/repo.git
#
# 安装到: $HOME/mini-hermes
# 命令:   mini-hermes

set -e

INSTALL_DIR="${HOME}/.local/bin"
WRAPPER_NAME="mini-hermes"
TARGET_DIR="${HOME}/mini-hermes"
DEFAULT_GIT_URL="https://github.com/notfresh/mini-hermes-v2.git"

# ── 参数解析 ─────────────────────────────────────────────────────────────────
# 支持: sh install.sh <url> 或 curl | sh -- <url>
if [ -n "${1:-}" ]; then
    GIT_URL="$1"
else
    GIT_URL="$DEFAULT_GIT_URL"
fi

# ── 清理旧环境 ───────────────────────────────────────────────────────────────
cleanup() {
    if [ -d "$TARGET_DIR" ]; then
        echo "🗑  清理旧安装: $TARGET_DIR"
        rm -rf "$TARGET_DIR"
    fi
}

# ── 克隆仓库 ─────────────────────────────────────────────────────────────────
clone() {
    echo "🔽 克隆仓库 ..."
    git clone --depth=1 "$GIT_URL" "$TARGET_DIR"
}

# ── 创建虚拟环境并安装依赖 ────────────────────────────────────────────────────
setup_venv() {
    echo "🐍 创建虚拟环境 ..."
    python3 -m venv "${TARGET_DIR}/.venv"

    echo "📦 安装依赖 ..."
    "${TARGET_DIR}/.venv/bin/pip" install -q --upgrade pip
    "${TARGET_DIR}/.venv/bin/pip" install -q -e "${TARGET_DIR}"
}

# ── 安装 wrapper ──────────────────────────────────────────────────────────────
install_wrapper() {
    mkdir -p "$INSTALL_DIR"
    wrapper="${INSTALL_DIR}/${WRAPPER_NAME}"

    cat > "$wrapper" << WRAPPER_EOF
#!/bin/sh
# mini-hermes — minimal-agent-v2 CLI wrapper

set -e
MINIHERMES_DIR="${TARGET_DIR}"
VENV_PYTHON="\${MINIHERMES_DIR}/.venv/bin/python3"
exec "\$VENV_PYTHON" "\$MINIHERMES_DIR/cli.py" "\$@"
WRAPPER_EOF

    chmod +x "$wrapper"
    echo "✅ mini-hermes → $wrapper"
}

# ── 检查 PATH ────────────────────────────────────────────────────────────────
check_path() {
    case ":$PATH:" in
        *:${INSTALL_DIR}:*) ;;
        *)
            echo ""
            echo "⚠  ${INSTALL_DIR} 不在 PATH 中。"
            echo "   添加到 ~/.bashrc / ~/.zshrc："
            echo ""
            echo "   export PATH=\"\$HOME/.local/bin:\$PATH\""
            echo ""
            ;;
    esac
}

# ── 主流程 ───────────────────────────────────────────────────────────────────
main() {
    echo ""
    echo "┌─────────────────────────────────────────┐"
    echo "│   MiniHermes  安装中                    │"
    echo "│   仓库: $GIT_URL"
    echo "│   目标: $TARGET_DIR"
    echo "└─────────────────────────────────────────┘"
    echo ""

    cleanup
    clone
    setup_venv
    install_wrapper
    check_path

    echo ""
    echo "✅ 安装完成!"
    echo ""
    echo "   运行:  mini-hermes"
    echo "   源码:  $TARGET_DIR"
    echo ""
}

main

#!/usr/bin/env bash
# install-local.sh — 本地已有项目时，仅安装 mini-hermes wrapper 到 ~/.local/bin
# 用法: ./install-local.sh
# 卸载: rm ~/.local/bin/mini-hermes

set -euo pipefail

INSTALL_DIR="${HOME}/.local/bin"
WRAPPER_NAME="mini-hermes"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="${SCRIPT_DIR}/.venv/bin/python3"

# ── 依赖检查 ─────────────────────────────────────────────────────────────────
if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "错误: 找不到虚拟环境 Python: $VENV_PYTHON" >&2
    echo "提示: 先运行 python3 -m venv .venv 创建虚拟环境" >&2
    exit 1
fi

# ── 创建安装目录 ─────────────────────────────────────────────────────────────
mkdir -p "$INSTALL_DIR"
WRAPPER_PATH="${INSTALL_DIR}/${WRAPPER_NAME}"

# ── 生成 wrapper（绝对路径） ───────────────────────────────────────────────────
cat > "$WRAPPER_PATH" << WRAPPER_EOF
#!/usr/bin/env bash
# mini-hermes — minimal-agent-v2 CLI wrapper
# 由 install-local.sh 生成，移动项目目录后请重新运行 ./install-local.sh

set -euo pipefail

MINIHERMES_DIR="${SCRIPT_DIR}"
VENV_PYTHON="\${MINIHERMES_DIR}/.venv/bin/python3"

exec "\$VENV_PYTHON" "\$MINIHERMES_DIR/cli.py" "\$@"
WRAPPER_EOF

# 替换 SCRIPT_DIR 模板变量
sed -i "s|\${SCRIPT_DIR}|${SCRIPT_DIR}|g" "$WRAPPER_PATH"

chmod +x "$WRAPPER_PATH"

# ── PATH 检查 ────────────────────────────────────────────────────────────────
if [[ ":$PATH:" != *":${INSTALL_DIR}:"* ]]; then
    echo ""
    echo "⚠  ${INSTALL_DIR} 不在 PATH 中。"
    echo "   请将以下内容添加到 ~/.bashrc 或 ~/.zshrc："
    echo ""
    echo "   export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo ""
fi

echo "✅ mini-hermes 已安装到: $WRAPPER_PATH"

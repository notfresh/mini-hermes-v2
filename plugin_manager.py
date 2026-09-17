"""
plugin_manager.py — V2 插件管理（commit 1/4：managed copy + git clone）

设计目标：
  - V2 作为宿主，能从 git URL 装外部插件（参照 Claude Code / Kimi Code 的协议）
  - 插件安装到 ~/.minimal-agent-v2/plugins/managed/<id>/（managed copy，隔离原仓库）
  - 装/卸/列表 三条命令；本 commit 只实现这三条，manifest 解析/skill 注入/tool 加载留后续 commit

协议（按 2026-09-15 与郑旭讨论定稿）：
  - install/list/remove 命令通过 cli.py 的早期 dispatch 进入
  - 不依赖 pyproject.toml 或 v2 的现有 import 结构（纯 stdlib）
  - git clone 走 subprocess；不调 api.github.com（与 Kimi Code 一致，国内环境友好）

后续 commit：
  - commit 2: manifest loader（读 .claude-plugin/plugin.json 8 字段）
  - commit 3: skill 注册 + bootstrap 多注入（turn_context 拼接 system prompt）
  - commit 4: tools/*.py importlib 加载 + shell hook 回调
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

# 复借 V2 现有的全局配置目录约定（与 config.py:33 get_config_dir() 同源）
PLUGINS_ROOT = Path("~/.minimal-agent-v2/plugins").expanduser()
MANAGED_DIR = PLUGINS_ROOT / "managed"
INSTALLED_FILE = PLUGINS_ROOT / "installed.json"

# 不合法 id 字符（防止路径注入 / 与文件系统冲突）
_ID_SAFE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")


def _resolve_id_from_url(url: str) -> str:
    """从 git URL 推断插件 id。例：
        https://github.com/notfresh/axgraph           -> axgraph
        https://github.com/notfresh/axgraph.git      -> axgraph
        git@github.com:notfresh/axgraph.git         -> axgraph
        https://github.com/notfresh/axgraph/releases/tag/v0.1.0 -> axgraph

    不支持 https://github.com/owner/repo/tree/<ref> —— 那是浏览器专用 URL，
    git clone 拒绝。要 pin ref 请用 --ref <ref> 而不是 URL 里嵌 ref。
    """
    if "/tree/" in url or "/blob/" in url:
        sys.exit(
            f"plugin: {url} 是浏览器 URL（/tree/ 或 /blob/）\n"
            f"  改用 https://github.com/owner/repo + --ref <ref>"
        )
    url = url.rstrip("/").removesuffix(".git")
    # 兼容 ssh / https / releases/tag
    url = re.sub(r"/releases/tag/.*$", "", url)
    parts = re.split(r"[:/]", url)
    for p in reversed(parts):
        if p and p not in ("github.com", "gitlab.com", "bitbucket.org"):
            return p.lower()
    raise ValueError(f"plugin: cannot infer id from URL {url!r}")


def install(url: str, ref: str | None = None) -> str:
    """git clone <url> 到 ~/.minimal-agent-v2/plugins/managed/<id>/

    返回 plugin id。如果目录已存在，直接复用（idempotent），不再 clone。
    ref 可选：branch/tag/sha，与 git clone -b <ref> 同效。
    """
    pid = _resolve_id_from_url(url)
    if not _ID_SAFE.match(pid):
        sys.exit(f"plugin: inferred id {pid!r} fails safety check ({_ID_SAFE.pattern})")
    target = MANAGED_DIR / pid

    MANAGED_DIR.mkdir(parents=True, exist_ok=True)

    if target.exists():
        print(f"plugin: {pid} already installed at {target} — skipping clone")
        print(f"        (use `v2 plugin remove {pid}` first if you want to reinstall)")
    else:
        print(f"plugin: cloning {url} → {target}")
        cmd = ["git", "clone", "--depth", "1"]
        if ref:
            cmd += ["--branch", ref]
        cmd += [url, str(target)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(
                f"plugin: git clone failed (exit={r.returncode})\n"
                f"  stderr: {r.stderr.strip()}"
            )

    # 记录到 installed.json（commit 2 起会让 manifest loader 读这份）
    _record_install(pid, url, ref)
    print(f"plugin: ✓ installed {pid} (managed copy at {target})")
    return pid


def remove(pid: str) -> None:
    """删除 managed copy + 从 installed.json 摘除。"""
    if not _ID_SAFE.match(pid):
        sys.exit(f"plugin: invalid id {pid!r}")
    target = MANAGED_DIR / pid
    if not target.exists():
        sys.exit(f"plugin: {pid} not installed (no managed copy at {target})")
    print(f"plugin: removing {target}")
    shutil.rmtree(target)
    _forget_install(pid)
    print(f"plugin: ✓ removed {pid}")


def list_installed() -> list[dict]:
    """列出已装插件（从 installed.json 读，附带 managed copy 状态）。"""
    if not INSTALLED_FILE.exists():
        return []
    import json
    records = json.loads(INSTALLED_FILE.read_text())
    out = []
    for pid, meta in records.items():
        target = MANAGED_DIR / pid
        out.append({
            "id": pid,
            "url": meta.get("url", ""),
            "ref": meta.get("ref"),
            "managed": str(target),
            "present": target.exists(),
            "installed_at": meta.get("installed_at", ""),
        })
    return out


def _record_install(pid: str, url: str, ref: str | None) -> None:
    import json
    from datetime import datetime, timezone
    PLUGINS_ROOT.mkdir(parents=True, exist_ok=True)
    records = {}
    if INSTALLED_FILE.exists():
        records = json.loads(INSTALLED_FILE.read_text())
    records[pid] = {
        "url": url,
        "ref": ref,
        "installed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    INSTALLED_FILE.write_text(json.dumps(records, indent=2, ensure_ascii=False))


def _forget_install(pid: str) -> None:
    import json
    if not INSTALLED_FILE.exists():
        return
    records = json.loads(INSTALLED_FILE.read_text())
    records.pop(pid, None)
    INSTALLED_FILE.write_text(json.dumps(records, indent=2, ensure_ascii=False))


# ── CLI dispatch（被 cli.py main() 早期调用）──

def _run_plugin_command(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="v2 plugin",
        description="V2 插件管理（commit 1/4：managed copy + git clone）",
    )
    sub = parser.add_subparsers(dest="cmd", metavar="<subcommand>")

    p_install = sub.add_parser("install", help="从 git URL 装插件到 managed copy")
    p_install.add_argument("url", help="GitHub/GitLab 等 git URL；4 种 URL 形式都认")
    p_install.add_argument("--ref", help="branch/tag/sha，与 git clone -b 同效")

    sub.add_parser("list", help="列出已装插件")

    p_remove = sub.add_parser("remove", help="删除插件的 managed copy")
    p_remove.add_argument("id", help="plugin id")

    p_info = sub.add_parser("info", help="展示插件 manifest 元信息（commit 2/4）")
    p_info.add_argument("id", help="plugin id")

    p_tools = sub.add_parser("tools", help="加载并展示插件 lib/*.py 加载的模块（commit 4/4 兼容未来 Python-first plugin）")
    p_tools.add_argument("id", help="plugin id")

    args = parser.parse_args(argv)

    if args.cmd == "install":
        install(args.url, args.ref)
    elif args.cmd == "list":
        rows = list_installed()
        if not rows:
            print("(no plugins installed)")
            return
        print(f"{'id':<24} {'ref':<16} {'present':<8} url")
        print("─" * 80)
        for r in rows:
            print(f"{r['id']:<24} {(r['ref'] or '-'):<16} {('yes' if r['present'] else 'NO'):<8} {r['url']}")
    elif args.cmd == "remove":
        remove(args.id)
    elif args.cmd == "info":
        # commit 2：委托 plugin_manifest.info_command
        import plugin_manifest
        plugin_manifest.info_command(args.id)
    elif args.cmd == "tools":
        # commit 4：委托 plugin_tools.tools_command
        import plugin_tools
        plugin_tools.tools_command(args.id)
    else:
        parser.print_help()

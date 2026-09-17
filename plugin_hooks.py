"""
plugin_hooks.py — V2 插件 hook 执行器（commit 4/4）

本 commit 范围：
  - plugin manifest 的 hooks 字段（指向 hooks/hooks.json）→ 解析
    SessionStart 事件 → 调 shell hook（subprocess 捕 stdout JSON）
  - 支持 plugin.py:on_session_start(ctx) Python 回调（commit 4 协议）
  - 两种 hook 都按 (plugin_id, event) 注册，返回的 stdout JSON 或
    Python 返回值都作为 'additionalContext' 拼进 system prompt

协议（2026-09-15 与郑旭讨论定稿）：
  - shell hook 字段名（additionalContext）与 Claude Code 兼容
    —— 我们读 JSON 时优先 additionalContext，fallback additional_context
    （这两个在不同版本 Claude Code 上分别被读，不一致）
  - Python 回调优先：plugin.py:on_session_start(ctx) 比 shell hook 优先
    调（plugin 可以提供 Python hook 而不必有 hooks.json）
"""

from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

import plugin_manager


_SESSION_START_EVENT = "SessionStart"
_HOOK_TIMEOUT_SEC = 5


# ── Shell hook 执行 ──

def _run_shell_hook(hook_command: str, cwd: Path, timeout: int = _HOOK_TIMEOUT_SEC) -> str:
    """执行 shell hook，捕获 stdout 中 Claude Code 风格的 JSON。

    Claude Code SessionStart hook 输出形如：
        {"hookSpecificOutput": {"hookEventName": "SessionStart",
                                "additionalContext": "<markdown>"}}
    我们解析这个结构，返回 additionalContext 内容（str）。

    失败兜底：
      - JSON parse 失败 → 把整个 stdout 当 markdown 返回（不阻断）
      - subprocess 失败 → 返回空串
    """
    try:
        r = subprocess.run(
            hook_command,
            shell=True,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        print(f"plugin: shell hook timeout ({timeout}s): {hook_command!r}", file=sys.stderr)
        return ""
    except Exception as e:
        print(f"plugin: shell hook exec failed: {e}", file=sys.stderr)
        return ""

    if r.returncode != 0:
        print(f"plugin: shell hook exit {r.returncode}: {r.stderr.strip()}", file=sys.stderr)
        # 仍然尝试解析 stdout——有些 hook 即便非零也输出有用内容

    stdout = r.stdout.strip()
    if not stdout:
        return ""

    # 优先解析 Claude Code v2.1+ 格式
    try:
        d = json.loads(stdout)
        # 嵌套路径：hookSpecificOutput.additionalContext
        nested = d.get("hookSpecificOutput", {})
        if isinstance(nested, dict):
            ctx = nested.get("additionalContext")
            if isinstance(ctx, str):
                return ctx
        # fallback：additional_context（Cursor / 旧版 Claude Code）
        ctx = d.get("additional_context")
        if isinstance(ctx, str):
            return ctx
        # 都没有：把 stdout 整个当 markdown
        return stdout
    except json.JSONDecodeError:
        # 不是 JSON，整个 stdout 当 markdown
        return stdout


# ── Python 回调加载 ──

def _load_python_hook(pid: str) -> Optional[callable]:
    """加载 plugin 的 plugin.py:on_session_start(ctx) 回调（如果存在）。

    返回可调用对象；不存在返回 None。
    """
    import plugin_manifest
    m = plugin_manifest.load_manifest(pid)
    if m is None:
        return None
    plugin_py = m.root / "plugin.py"
    if not plugin_py.is_file():
        return None

    mod_name = f"_plugin_{pid}_plugin"
    spec = importlib.util.spec_from_file_location(mod_name, plugin_py)
    if spec is None or spec.loader is None:
        return None
    try:
        mod = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = mod
        spec.loader.exec_module(mod)
    except Exception as e:
        print(f"plugin: {pid} plugin.py import failed: {e}", file=sys.stderr)
        return None

    fn = getattr(mod, "on_session_start", None)
    if not callable(fn):
        return None
    return fn


# ── 组合 dispatch ──

def run_session_start_hooks() -> str:
    """对每个已装 plugin 跑 SessionStart hook，按 plugin id 字典序拼接。

    返回值：所有 hook 输出（markdown 字符串）的拼接。
    每个 plugin 自己的输出用 --- <plugin_id> --- 分隔，便于模型识别。
    """
    if not plugin_manager.MANAGED_DIR.is_dir():
        return ""

    out_chunks: list[str] = []
    for pid in sorted(_installed_plugin_ids()):
        chunk = _run_single_plugin_session_start(pid)
        if chunk:
            out_chunks.append(f"--- {pid} (SessionStart hook) ---\n{chunk}")

    if not out_chunks:
        return ""

    return (
        "<PLUGIN_HOOKS>\n"
        "The following content was injected by each plugin's SessionStart hook.\n"
        "Read it before responding to any user request — these are non-negotiable\n"
        "behavioral rules contributed by the installed plugins.\n\n"
        + "\n\n".join(out_chunks)
        + "\n</PLUGIN_HOOKS>"
    )


def _run_single_plugin_session_start(pid: str) -> str:
    """跑单个 plugin 的 SessionStart hook（Python 回调优先于 shell）。"""
    # 1. Python 回调优先
    py_hook = _load_python_hook(pid)
    if py_hook is not None:
        try:
            ctx = {"plugin_id": pid}
            result = py_hook(ctx)
            if isinstance(result, str):
                return result
            if isinstance(result, dict):
                return result.get("additionalContext", json.dumps(result, ensure_ascii=False))
            return str(result) if result is not None else ""
        except Exception as e:
            print(f"plugin: {pid} on_session_start raised: {e}", file=sys.stderr)
            # 失败回退到 shell hook

    # 2. Shell hook fallback（manifest 声明 hooks 字段）
    import plugin_manifest
    m = plugin_manifest.load_manifest(pid)
    if m is None or not m.hooks_path:
        return ""
    hooks_json = (m.root / m.hooks_path).resolve()
    if not hooks_json.is_file():
        return ""

    try:
        hooks_data = json.loads(hooks_json.read_text())
    except json.JSONDecodeError as e:
        print(f"plugin: {pid} hooks.json parse failed: {e}", file=sys.stderr)
        return ""

    # 只关心 SessionStart 事件
    for hook in hooks_data.get("hooks", []):
        if hook.get("event") != _SESSION_START_EVENT:
            continue
        # matcher 不强制要求
        cmd = hook.get("command", "")
        timeout = hook.get("timeout", _HOOK_TIMEOUT_SEC)
        if cmd:
            return _run_shell_hook(cmd, cwd=m.root, timeout=timeout)

    return ""


def _installed_plugin_ids() -> list[str]:
    """从 installed.json 读 plugin id 列表（顺序确定）。"""
    if not plugin_manager.INSTALLED_FILE.exists():
        return []
    return list(json.loads(plugin_manager.INSTALLED_FILE.read_text()).keys())

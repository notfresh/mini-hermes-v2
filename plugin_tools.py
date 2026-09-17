"""
plugin_tools.py — V2 插件 tool 加载器（commit 4/4，兼容未来 Python-first plugin）

设计目标：
  - 加载已装 plugin 的 lib/*.py 文件作为 Python 模块
  - import 副作用自动触发 @tool 装饰器注册到 V2 _TOOL_REGISTRY
  - 暴露 v2 plugin tools <id> 命令行：列出该 plugin 加载的模块

重要事实（郑旭 2026-09-15 指出）：
  axgraph 自己的 lib/*.py（graph_query / purity / diagnose /
  call_candidates / update_graph）是 CLI 依赖脚本，不是 @tool 装饰
  的 Python 函数。它们提供 `python3 bin/ax ...` CLI 接口，不直接
  注册成 agent 可调用的工具。

  因此：
    - 当前 plugin 装上后 _TOOL_REGISTRY 增量为 0（符合预期）
    - 这个加载器是为未来"Python-first plugin"留的协议位
      ——即 plugin.py 或 lib/*.py 里直接 import V2 的 @tool 装饰
      器，把函数注册成 LLM 可调用工具
    - 这种 plugin 现在还没有示例，但保留加载通路 + CLI 入口
      避免以后重新设计

协议（2026-09-15 与郑旭讨论定稿）：
  - 加载路径：扫 ~/.minimal-agent-v2/plugins/managed/<id>/lib/*.py
  - 命名空间：每个 plugin 的 lib 单独占一个模块名空间
    ——例 axgraph 的 graph_query.py → _plugin_axgraph_graph_query
  - 失败不阻断：单个文件加载失败打 WARN 继续下一个
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import plugin_manager


def _load_plugin_lib(pid: str) -> list[str]:
    """加载 plugin 的 lib/*.py 文件，返回成功加载的模块名列表。"""
    import plugin_manifest
    m = plugin_manifest.load_manifest(pid)
    if m is None:
        return []

    lib_dir = m.root / "lib"
    if not lib_dir.is_dir():
        return []

    loaded: list[str] = []
    for py in sorted(lib_dir.glob("*.py")):
        if py.name == "__init__.py":
            continue
        mod_name = f"_plugin_{pid}_{py.stem}"
        spec = importlib.util.spec_from_file_location(mod_name, py)
        if spec is None or spec.loader is None:
            print(f"plugin: {pid} {py.name} spec load failed", file=sys.stderr)
            continue
        try:
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
            loaded.append(mod_name)
        except Exception as e:
            print(f"plugin: {pid} {py.name} import failed: {e}", file=sys.stderr)
            sys.modules.pop(mod_name, None)
    return loaded


def load_all_plugin_tools() -> dict[str, list[str]]:
    """加载所有已装 plugin 的 tools。返回 {plugin_id: [module_name, ...]}。"""
    out: dict[str, list[str]] = {}
    if not plugin_manager.MANAGED_DIR.is_dir():
        return out
    for pid in sorted(_installed_plugin_ids()):
        loaded = _load_plugin_lib(pid)
        if loaded:
            out[pid] = loaded
    return out


def _installed_plugin_ids() -> list[str]:
    if not plugin_manager.INSTALLED_FILE.exists():
        return []
    import json
    return list(json.loads(plugin_manager.INSTALLED_FILE.read_text()).keys())


# ── CLI dispatch ──

def tools_command(pid: str) -> None:
    """v2 plugin tools <id>：列出 plugin lib/*.py 加载的模块名。

    实际 @tool 装饰的函数已经通过 import 副作用注册到 V2 的
    _TOOL_REGISTRY / _TOOL_SCHEMAS；本命令只展示模块加载状态。
    """
    loaded = _load_plugin_lib(pid)
    if not loaded:
        print(f"plugin: {pid} 没有 lib/*.py 或全部加载失败")
        return
    print(f"plugin: {pid} 加载的工具模块：")
    for mod_name in loaded:
        print(f"  · {mod_name}")
    print()
    print("(模块里 @tool 装饰的函数已注册到 V2 _TOOL_REGISTRY；")
    print(" 用 v2 --list-tools 看完整工具清单)")

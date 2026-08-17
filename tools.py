#!/usr/bin/env python3
"""
tools.py — MinimalAgentV2 内置工具集
======================================

Hermes 对应: tools/file_tools.py + tools/terminal_tool.py

传承自 MinimalAgentV1 tools.py：
  - @tool 装饰器注册（自动生成 JSON Schema）
  - 内置工具：read / write / ls / grep / find / head / bash
  - 新增：get_time（北京时间）、calculator（安全计算器）

工具的错误会作为 Observation 回填给 LLM（不是崩溃）——
这是 Agent 能从失败中继续推理的关键设计。
"""

from __future__ import annotations

import datetime
import os
import pathlib
import subprocess

from tool_runner import tool


# ── 技能框架：load_skill 工具（挂载点）──────────────────────────────────
# 对应 Hermes tools/skills_tool.py 的 skill_view：按需加载技能全文。
# registry 由 CLI 启动时注入（SkillRegistry 实例）。

_registry: "SkillRegistry | None" = None


def set_registry(registry: "SkillRegistry") -> None:
    """由 CLI 注入技能注册表（load_skill 工具的背后实现）。"""
    global _registry
    _registry = registry


@tool(description="加载一个技能（skill）的完整内容。技能是经过验证的工作方法，包含强制步骤和 Red Flags 检查表。调用后必须严格按技能流程执行。可用技能列表见系统提示词的 <available_skills> 块。")
def load_skill(name: str) -> str:
    """Load a skill's full content.

    Args:
        name: 技能名，如 'brainstorming'、'systematic-debugging'
    """
    if _registry is None:
        return "Error: 技能系统未启用（未注入 SkillRegistry）"
    content = _registry.load(name)
    if content is None:
        available = ", ".join(s["name"] for s in _registry.list_skills())
        return f"Error: 技能 '{name}' 不存在。可用技能: {available}"
    return content


# ── 内置工具（传承 V1）─────────────────────────────────────────────────────


@tool(description="获取当前北京时间（UTC+8），返回格式化字符串")
def get_time() -> str:
    """获取当前北京时间。

    服务器时区已是 Asia/Shanghai，本地时间即北京时间。
    """
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " (北京时间)"


@tool(description="计算数学表达式，如 '(3+5)*2' 返回 16")
def calculator(expression: str) -> str:
    """Calculate a math expression.

    Args:
        expression: 要计算的数学表达式，如 (3+5)*2
    """
    allowed = set("0123456789+-*/(). %")
    if not all(c in allowed for c in expression):
        return "错误：表达式包含不允许的字符"
    try:
        result = eval(expression, {"__builtins__": {}}, {})  # noqa: S307
        return f"{expression} = {result}"
    except Exception as e:
        return f"错误：无法计算（{e}）"


@tool(description="读取文件内容（可指定行数上限）")
def read(path: str, limit: int = 50) -> str:
    """Read a text file.

    Args:
        path: 文件路径（绝对或相对路径）
        limit: 最多读取的行数，默认 50
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        content = "".join(lines[:limit])
        total = len(lines)
        shown = min(limit, total)
        return f"--- {path} ({total} lines, showing {shown}) ---\n{content}"
    except Exception as e:
        return f"Error reading {path}: {e}"


@tool(description="写入内容到文件（自动创建父目录）")
def write(path: str, content: str) -> str:
    """Write content to a file (overwrites if exists).

    Args:
        path: 文件路径
        content: 要写入的文本内容
    """
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Written {len(content)} chars to {path}"
    except Exception as e:
        return f"Error writing {path}: {e}"


@tool(description="列出目录内容（📁 目录 / 📄 文件 + 大小）")
def ls(path: str = ".") -> str:
    """List directory contents.

    Args:
        path: 目录路径，默认当前目录
    """
    try:
        entries = sorted(
            pathlib.Path(path).iterdir(),
            key=lambda x: (not x.is_dir(), x.name.lower()),
        )
        if not entries:
            return f"(empty: {path})"
        lines = []
        for e in entries:
            marker = "📁" if e.is_dir() else "📄"
            size = f"  {e.stat().st_size:,}B" if e.is_file() else ""
            lines.append(f"{marker} {e.name}{size}")
        return f"--- {path} ({len(entries)} entries) ---\n" + "\n".join(lines)
    except Exception as e:
        return f"Error: {e}"


@tool(description="在文件中搜索文本（正则匹配，递归子目录）")
def grep(pattern: str, path: str = ".") -> str:
    """Search file contents using regex.

    Args:
        pattern: 搜索的正则表达式
        path: 搜索路径（文件或目录），默认当前目录
    """
    try:
        result = subprocess.run(
            ["grep", "-rn", "--color=never", pattern, path],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            preview = "\n".join(lines[:100])
            if len(lines) > 100:
                preview += f"\n... ({len(lines) - 100} more matches)"
            return preview
        elif result.returncode == 1:
            return "(no matches)"
        else:
            return f"Error: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return "Error: grep timed out"
    except Exception as e:
        return f"Error: {e}"


@tool(description="按文件名模式搜索文件（glob 风格通配符）")
def find(pattern: str, path: str = ".") -> str:
    """Find files by name pattern (glob style).

    Args:
        pattern: 文件名模式，如 '*.py'、'*test*'
        path: 搜索根目录，默认当前目录
    """
    try:
        result = subprocess.run(
            ["find", path, "-name", pattern, "-type", "f"],
            capture_output=True, text=True, timeout=15,
        )
        lines = [l for l in result.stdout.strip().split("\n") if l]
        if not lines:
            return "(no files found)"
        preview = "\n".join(lines[:100])
        if len(lines) > 100:
            preview += f"\n... ({len(lines) - 100} more files)"
        return f"--- {len(lines)} files matching '{pattern}' ---\n{preview}"
    except subprocess.TimeoutExpired:
        return "Error: find timed out"
    except Exception as e:
        return f"Error: {e}"


@tool(description="查看文件前 N 行")
def head(path: str, lines: int = 10) -> str:
    """Show the first N lines of a file.

    Args:
        path: 文件路径
        lines: 行数，默认 10
    """
    return read(path=path, limit=lines)


@tool(description="执行 shell 命令并返回输出（超时 30 秒）")
def bash(command: str) -> str:
    """Execute a shell command and capture its output.

    Args:
        command: 要执行的 shell 命令
    """
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30,
        )
        parts = []
        if result.stdout:
            parts.append(result.stdout.strip())
        if result.stderr:
            parts.append(f"[stderr]\n{result.stderr.strip()}")
        if result.returncode != 0:
            parts.append(f"[exit code: {result.returncode}]")
        return "\n\n".join(parts) if parts else "(empty output)"
    except subprocess.TimeoutExpired:
        return "Error: command timed out (30s)"
    except Exception as e:
        return f"Error: {e}"


# ── 清单打印（传承 V1: list_tools）────────────────────────────────────────


def list_tools() -> None:
    """打印已注册工具清单到 stdout。"""
    from tool_runner import _TOOL_SCHEMAS
    for schema in _TOOL_SCHEMAS:
        fn = schema["function"]
        print(f"\n  {fn['name']}")
        print(f"    {fn['description']}")
        params = fn["parameters"]
        for name, info in params.get("properties", {}).items():
            req = " (required)" if name in params.get("required", []) else ""
            print(f"    - {name}: {info['type']}{req}")
    print(f"\n  共 {len(_TOOL_SCHEMAS)} 个工具")

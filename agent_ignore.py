#!/usr/bin/env python3
"""
agent_ignore.py — AgentIgnore 路径权限校验模块
================================================

Hermes 对应: 无（Hermes 工具执行无路径级权限控制）
Kimi 对应:   packages/agent-core/src/permission/policies/*（deny 守卫）

职责：
- 解析 AgentIgnore 配置文件（默认 ~/.minimal-agent-v2/AgentIgnore）
- 工具调用前校验路径权限（R 读 / W 写 / X 执行），命中规则且权限不足即拒绝

AgentIgnore 语法（每行一条规则）：
    绝对路径::权限码

    权限码 = 允许的权限（R/W/X 组合），缺哪个字母就禁止哪个操作：
        /home/user/.ssh::            完全禁止（不可读/写/执行）
        /home/user/private::R       只允许读（禁止写、禁止执行）
        /tmp/sandbox::WX            允许写和执行，禁止读

匹配规则（第一版，做减法）：
- 规则路径是目标路径的前缀（目录规则覆盖整棵子树），文件规则精确匹配
- 多条规则取权限交集：父目录禁止的权限，子目录规则加不回来（不做"开小窗"）
- 无规则命中 = 默认全允许（不改变 V2 现有行为）

设计文档：docs/design-20260817-agent-ignore.md
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional

# ── 权限码常量 ──────────────────────────────────────────────────────────────

_PERM_CHARS = frozenset("RWX")          # 合法权限字母
_ALL_PERMS = frozenset("RWX")           # 默认全允许


# ── 工具 → (权限, 路径参数名列表) 映射表 ──────────────────────────────────
# path_args=None 表示无显式路径参数（bash 从 command 字符串提取绝对路径）
# 未列出的工具（get_time/calculator/load_skill）无文件操作，不校验

_TOOL_PERM_SPEC: dict[str, tuple[str, Optional[list[str]]]] = {
    "read":  ("R", ["path"]),
    "ls":    ("R", ["path"]),
    "grep":  ("R", ["path"]),
    "find":  ("R", ["path"]),
    "head":  ("R", ["path"]),
    "write": ("W", ["path"]),
    "bash":  ("X", None),
}

# bash command 中提取绝对路径：以 / 开头，到空白或引号为止
_ABS_PATH_RE = re.compile(r'(?:^|\s)(/[^\s\'"]+)')


def _norm(path: str) -> str:
    """路径归一化：相对路径 → 绝对路径，去掉 ./ ../ 冗余段。

    用 normpath+abspath（不跟随符号链接；链接绕过是第一版已知局限，
    见设计文档 §6.5）。
    """
    return os.path.normpath(os.path.abspath(path))


class AgentIgnore:
    """AgentIgnore 规则集：解析文件 + 路径权限判定。

    文件不存在时不要构造本类——用 load_default()（返回 None 表示不启用）。
    """

    def __init__(self, rules: list[tuple[str, frozenset]]):
        # rules: [(归一化绝对路径, 允许的权限集)]，保持文件顺序
        self.rules = rules

    # ── 加载 ────────────────────────────────────────────────────────────

    @classmethod
    def load(cls, path: str | Path) -> "AgentIgnore":
        """从文件解析。空行/注释行忽略；非法行跳过并打印警告（不崩溃）。"""
        rules: list[tuple[str, frozenset]] = []
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        for line_no, raw in enumerate(lines, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "::" not in line:
                print(f"⚠️ AgentIgnore:{line_no}: 缺少 '::'，忽略: {raw!r}")
                continue
            rule_path, _, perms_str = line.partition("::")
            rule_path = rule_path.strip()
            perms = set(perms_str.strip().upper())
            if not rule_path:
                print(f"⚠️ AgentIgnore:{line_no}: 空路径，忽略: {raw!r}")
                continue
            if not perms.issubset(_PERM_CHARS):
                print(f"⚠️ AgentIgnore:{line_no}: 权限码只允许 R/W/X，忽略: {raw!r}")
                continue
            if not os.path.isabs(rule_path):
                print(f"⚠️ AgentIgnore:{line_no}: 路径必须是绝对路径，忽略: {raw!r}")
                continue
            rules.append((_norm(rule_path), frozenset(perms)))
        return cls(rules)

    @classmethod
    def load_default(cls) -> Optional["AgentIgnore"]:
        """加载默认位置 ~/.minimal-agent-v2/AgentIgnore；文件不存在返回 None。"""
        path = Path("~/.minimal-agent-v2/AgentIgnore").expanduser()
        if not path.is_file():
            return None
        return cls.load(path)

    # ── 判定 ────────────────────────────────────────────────────────────

    def allowed_perms(self, path: str) -> frozenset:
        """目标路径的最终允许权限 = 所有前缀命中规则的权限交集（做减法）。

        无命中 = 全允许；命中的规则越多，权限越收窄。
        """
        abs_path = _norm(path)
        allowed = set(_ALL_PERMS)
        for rule_path, rule_perms in self.rules:
            if abs_path == rule_path or abs_path.startswith(rule_path + os.sep):
                allowed &= rule_perms
        return frozenset(allowed)

    def check_path(self, path: str, perm: str) -> Optional[str]:
        """校验单路径单权限。允许返回 None；拒绝返回原因字符串。"""
        allowed = self.allowed_perms(path)
        if perm not in allowed:
            return (
                f"AgentIgnore 权限校验失败: {path} 不允许 {perm} 操作 "
                f"(允许: {'/'.join(sorted(allowed)) or '无'})"
            )
        return None

    def check_tool(self, fn_name: str, fn_args: dict) -> Optional[str]:
        """工具调用前校验（ToolRunner.execute 检查点调用）。

        命中规则且权限不足 → 返回拒绝原因（作为错误 Observation 回填给 LLM）；
        未命中规则或工具无文件操作 → 返回 None（放行）。

        Args:
            fn_name: 工具名
            fn_args: 已解析的工具参数 dict
        """
        spec = _TOOL_PERM_SPEC.get(fn_name)
        if spec is None:
            return None  # 无文件操作的工具不校验
        perm, path_args = spec
        if path_args is not None:
            for key in path_args:
                raw = fn_args.get(key)
                if not raw:
                    continue  # 参数缺失/默认值场景不误伤（如 ls 默认 "." 总会传值）
                reason = self.check_path(str(raw), perm)
                if reason:
                    return reason
        elif fn_name == "bash":
            # bash 无路径参数：从 command 提取绝对路径，按 X（执行）校验。
            # 局限：内嵌 cat/rm 的 R/W 语义无法判断，见设计文档 §6.5。
            cmd = str(fn_args.get("command", ""))
            for path in _ABS_PATH_RE.findall(cmd):
                reason = self.check_path(path, "X")
                if reason:
                    return reason
        return None

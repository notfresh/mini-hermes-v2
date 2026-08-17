#!/usr/bin/env python3
"""
skill_registry.py — 技能注册表（技能框架挂载：新模块 1/2）
=============================================================

Superpowers 对应：skills/ 目录约定 —— 一个技能 = 一个目录 + 一个 SKILL.md。
Hermes 对应：tools/skills_tool.py + agent/prompt_builder.py 的 build_skills_system_prompt
             （渐进式披露：索引只给 name+description，全文按需加载）。
Kimi Code 对应：packages/agent-core/src/skill/ 的 SkillDefinition + registry。

职责：
  1. 扫描 skills/ 目录，解析每个 SKILL.md 的 frontmatter（name/description）
  2. 按需加载技能全文（load_skill 工具的背后实现）
  3. 生成技能索引文本（注入系统提示词，Hermes 式 <available_skills> 块）

扩展性落点：加一个新技能 = 在 skills/ 下放一个 SKILL.md 文件，零代码改动。
"""

from __future__ import annotations

import pathlib
import re
from typing import Dict, List, Optional

SKILL_FILE = "SKILL.md"
FM_START = "---"
# 技能总开关的约定名（bootstrap 技能；与 Superpowers 原版一致）
BOOTSTRAP_SKILL = "using-superpowers"


class SkillRegistry:
    """扫描并加载技能文件。

    Args:
        skills_dir: skills/ 根目录路径（默认：与本文件同级的 skills/）
    """

    def __init__(self, skills_dir: Optional[str] = None):
        if skills_dir is None:
            skills_dir = str(pathlib.Path(__file__).parent / "skills")
        self.skills_dir = pathlib.Path(skills_dir)
        self._index: Dict[str, dict] = {}
        self.scan()

    # ── 目录扫描 ──────────────────────────────────────────────────────────

    def scan(self) -> None:
        """重新扫描 skills/ 目录，重建索引。

        约定：skills/<name>/SKILL.md，frontmatter 里必须有 name 和 description。
        """
        self._index = {}
        if not self.skills_dir.is_dir():
            return
        for skill_dir in sorted(self.skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            skill_file = skill_dir / SKILL_FILE
            if not skill_file.is_file():
                continue
            meta = self._parse_frontmatter(skill_file.read_text(encoding="utf-8"))
            name = meta.get("name", skill_dir.name)
            self._index[name] = {
                "path": str(skill_file),
                "description": meta.get("description", ""),
            }

    # ── 查询接口 ──────────────────────────────────────────────────────────

    def list_skills(self) -> List[dict]:
        """返回 [{name, description}]。"""
        return [
            {"name": name, "description": meta["description"]}
            for name, meta in sorted(self._index.items())
        ]

    def has_skill(self, name: str) -> bool:
        return name in self._index

    def load(self, name: str) -> Optional[str]:
        """加载技能全文（含 frontmatter）。技能不存在返回 None。"""
        meta = self._index.get(name)
        if meta is None:
            return None
        return pathlib.Path(meta["path"]).read_text(encoding="utf-8")

    def has_bootstrap(self) -> bool:
        """技能包是否自带"技能总开关"（using-superpowers）。

        约定优于配置：宿主检测到总开关技能存在，就在会话开始时
        把它注入（Superpowers 式启动注入）。
        """
        return self.has_skill(BOOTSTRAP_SKILL)

    def index_text(self) -> str:
        """生成技能索引文本（Hermes 式：只列 name + description）。

        对应 Hermes agent/prompt_builder.py:1490 build_skills_system_prompt
        的 <available_skills> 块——注入系统提示词，让模型知道"有什么技能、
        什么场景该加载哪个"。全文仍由 load_skill 按需加载（渐进式披露）。
        """
        skills = self.list_skills()
        if not skills:
            return ""
        lines = ["<available_skills>", "你有以下技能可用（遇到相关场景必须先用 load_skill 工具加载全文再行动）："]
        for s in skills:
            lines.append(f"- {s['name']}: {s['description']}")
        lines.append("</available_skills>")
        return "\n".join(lines)

    # ── frontmatter 解析（零依赖简化版）────────────────────────────────────

    @staticmethod
    def _parse_frontmatter(text: str) -> Dict[str, str]:
        """解析 YAML frontmatter：只取 name 和 description 两个字段。"""
        result: Dict[str, str] = {}
        lines = text.splitlines()
        if not lines or lines[0].strip() != FM_START:
            return result
        for line in lines[1:]:
            if line.strip() == FM_START:
                break
            m = re.match(r"^(\w+):\s*(.*)$", line)
            if m and m.group(1) in ("name", "description"):
                value = m.group(2).strip().strip('"').strip("'")
                result[m.group(1)] = value
        return result

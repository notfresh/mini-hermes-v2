"""
plugin_manifest.py — V2 插件 manifest 加载器（commit 2/4）

本 commit 范围：
  - 读 .claude-plugin/plugin.json 的 8 标准字段（name/version/description/
    author/license/keywords/homepage/repository）+ skills/commands/hooks 路径声明
  - 解析 skills/ 目录下所有 skills/<name>/SKILL.md 的 frontmatter
    （commit 3 才会把 SKILL.md 灌进 system prompt）
  - 命令行：v2 plugin info <id>，展示已装插件的 manifest 元信息
  - commands 字段 V2 不支持：装/查时 WARN，但不报错

本 commit 不做：
  - 不调 turn_context / conversation_loop
  - 不修改 SkillRegistry
  - 不执行 hooks/*.sh（commit 4）
  - 不 importlib 加载 tools/*.py（commit 4）

协议参考（2026-09-15 与郑旭讨论定稿）：
  - manifest 字段完全照搬 Claude Code plugin.json schema
  - Kimi 的 sessionStart.skill 字段 V2 不识别（静默忽略）
  - 第三方 plugin 也可自定义 pythonDependencies 块（V2 只读不写）
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Optional

import plugin_manager


# ── Manifest 数据类（dict-based，保持简单；不引入 pydantic） ──

# Claude Code plugin.json 标准字段 + 我们关心的路径声明字段
_KNOWN_KEYS = {
    "name", "version", "description",
    "author", "license", "keywords", "homepage", "repository",
    "skills", "commands", "hooks",
    # Kimi / 自定义扩展字段（V2 静默忽略，不 WARN）
    "sessionStart", "systemPrompt", "systemPromptPath", "mcpServers",
    "interface", "pythonDependencies",
    # Claude Code 顶层元字段（仓库根 .claude-plugin/marketplace.json 风格）
    "$schema", "owner", "renames",
}

# V2 不支持的 manifest 字段——读到时 WARN（不报错）
_UNSUPPORTED_BY_V2 = {
    "commands": "commands/*.md 是 Claude/Kimi slash 命令语义，V2 无 TUI；commands/ 目录会被忽略",
}


class PluginManifest:
    """单个插件的 manifest 解析结果。"""

    def __init__(self, pid: str, plugin_root: Path, raw: dict):
        self.id = pid
        self.root = plugin_root
        self.raw = raw
        self.name = raw.get("name", pid)
        self.version = raw.get("version", "0.0.0")
        self.description = raw.get("description", "")
        self.author = raw.get("author", {})
        self.license = raw.get("license", "")
        self.homepage = raw.get("homepage", "")
        self.repository = raw.get("repository", "")
        self.keywords = raw.get("keywords", [])

        # 路径声明字段（相对 plugin_root）
        self.skills_path = raw.get("skills")  # "./skills/" 或 "./skills/using-x"
        self.commands_path = raw.get("commands")
        self.hooks_path = raw.get("hooks")    # "./hooks/hooks.json" 或 None

        # 解析后的 SKILL.md 列表（commit 3 会用）
        self.skills: list[SkillEntry] = []

        # V2 不支持字段的告警
        self.warnings: list[str] = []

    def __repr__(self) -> str:
        return f"<PluginManifest {self.id} v{self.version}>"


class SkillEntry:
    """单个 SKILL.md 的解析结果（frontmatter name + description）。"""

    def __init__(self, plugin_id: str, rel_path: Path, abs_path: Path,
                 name: str, description: str):
        self.plugin_id = plugin_id
        self.rel_path = rel_path
        self.abs_path = abs_path
        self.name = name
        self.description = description

    def __repr__(self) -> str:
        return f"<SkillEntry {self.plugin_id}/{self.name}>"


# ── 加载入口 ──

def load_manifest(pid: str) -> Optional[PluginManifest]:
    """加载已装插件的 manifest；不存在/解析失败返回 None。"""
    plugin_root = plugin_manager.MANAGED_DIR / pid
    if not plugin_root.is_dir():
        print(f"plugin: {pid} not installed (no managed copy)", file=sys.stderr)
        return None

    # Claude Code 规范：manifest 在 .claude-plugin/plugin.json
    # Kimi Code 规范：kimi.plugin.json 或 .kimi-plugin/plugin.json
    candidates = [
        plugin_root / ".claude-plugin" / "plugin.json",
        plugin_root / "kimi.plugin.json",
        plugin_root / ".kimi-plugin" / "plugin.json",
    ]
    manifest_path = next((p for p in candidates if p.exists()), None)
    if manifest_path is None:
        print(f"plugin: {pid} has no manifest at {candidates[0]} (or kimi variants)", file=sys.stderr)
        return None

    try:
        raw = json.loads(manifest_path.read_text())
    except json.JSONDecodeError as e:
        print(f"plugin: {pid} manifest JSON parse failed: {e}", file=sys.stderr)
        return None

    m = PluginManifest(pid, plugin_root, raw)

    # 收集 V2 不支持的字段，warn 但不退出
    for key, reason in _UNSUPPORTED_BY_V2.items():
        if raw.get(key):
            m.warnings.append(f"manifest.{key} declared but {reason}")

    # 解析 skills/ 下的 SKILL.md（只读 frontmatter，不读 body）
    m.skills = _discover_skills(m)
    return m


_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(?P<meta>.*?)\n---\s*\n", re.DOTALL
)


def _parse_frontmatter(text: str) -> tuple[str, str]:
    """极简 YAML-frontmatter 解析——支持 name + description（含 |/> 块描述符）。

    拒绝展开 YAML 库依赖；agentskills.io 规范的 frontmatter 字段就 2 个。
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return "", ""
    meta_block = m.group("meta")
    name = ""
    description = ""
    in_block_desc = False
    block_indent_prefix = ""  # 用于判断"延续行"的最小前导空白

    for raw_line in meta_block.splitlines():
        # 块描述符的延续行：以空白开头
        if in_block_desc:
            if raw_line.startswith((" ", "\t")):
                stripped = raw_line.lstrip()
                # 记录首行的最小缩进作为基准（保证 '    a' 和 '    b' 都算延续）
                if not block_indent_prefix:
                    block_indent_prefix = raw_line[: len(raw_line) - len(stripped)]
                if stripped:
                    description += " " + stripped if description else stripped
                continue
            else:
                # 非空白起头的行 → 块描述结束
                in_block_desc = False
                block_indent_prefix = ""

        if raw_line.startswith("name:"):
            name = raw_line[len("name:"):].strip().strip('"').strip("'")
        elif raw_line.startswith("description:"):
            value = raw_line[len("description:"):].strip()
            if value in ("|", ">"):
                # 块描述符——下一行起收集延续内容
                in_block_desc = True
                block_indent_prefix = ""
                continue
            description = value.strip('"').strip("'")
    return name, description


def _discover_skills(m: PluginManifest) -> list[SkillEntry]:
    """扫 manifest 声明的 skills 目录，解析每个 SKILL.md 的 frontmatter。"""
    if not m.skills_path:
        return []

    skills_root = (m.root / m.skills_path).resolve()
    if not skills_root.is_dir():
        return []

    out: list[SkillEntry] = []
    # skills/<name>/SKILL.md 形式（agentskills.io 规范）
    for skill_dir in sorted(skills_root.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.is_file():
            continue
        try:
            text = skill_file.read_text(encoding="utf-8")
        except Exception as e:
            print(f"plugin: {m.id} SKILL.md read failed {skill_file}: {e}", file=sys.stderr)
            continue
        name, desc = _parse_frontmatter(text)
        if not name:
            name = skill_dir.name  # fallback：用目录名
        out.append(SkillEntry(
            plugin_id=m.id,
            rel_path=skill_file.relative_to(m.root),
            abs_path=skill_file,
            name=name,
            description=desc,
        ))
    return out


# ── CLI dispatch ──

def info_command(pid: str) -> None:
    """v2 plugin info <id>：展示 manifest 解析结果 + warnings + skills。"""
    m = load_manifest(pid)
    if m is None:
        sys.exit(1)

    print(f"plugin: {m.id}")
    print(f"  version     : {m.version}")
    print(f"  description : {m.description}")
    if isinstance(m.author, dict):
        name = m.author.get("name", "")
        email = m.author.get("email", "")
        print(f"  author      : {name}{f' <{email}>' if email else ''}")
    elif m.author:
        print(f"  author      : {m.author}")
    if m.license:
        print(f"  license     : {m.license}")
    if m.homepage:
        print(f"  homepage    : {m.homepage}")
    if m.repository:
        print(f"  repository  : {m.repository}")
    if m.keywords:
        print(f"  keywords    : {', '.join(m.keywords)}")

    print()
    print(f"  manifest path  : {m.root / '.claude-plugin' / 'plugin.json'}")
    print(f"  skills path    : {m.skills_path or '(none)'}")
    print(f"  commands path  : {m.commands_path or '(none — V2 不支持 commands/*.md)'}")
    print(f"  hooks path     : {m.hooks_path or '(none)'}")

    if m.skills:
        print()
        print(f"  skills ({len(m.skills)}):")
        for s in m.skills:
            desc = (s.description or "").replace("\n", " ").strip()
            if len(desc) > 60:
                desc = desc[:57] + "..."
            print(f"    · {s.name:<28} {desc}")

    if m.warnings:
        print()
        print(f"  warnings ({len(m.warnings)}):")
        for w in m.warnings:
            print(f"    ⚠ {w}")

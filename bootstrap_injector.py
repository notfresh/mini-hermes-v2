#!/usr/bin/env python3
"""
bootstrap_injector.py — 启动注入器（技能框架挂载：新模块 2/2，整个框架的灵魂）
===============================================================================

Kimi Code 对应：packages/agent-core/src/agent/injection/injector.py
                （DynamicInjector 基类，39 行）
              + packages/agent-core/src/agent/injection/plugin-session-start.ts
                （PluginSessionStartInjector，把 plugin.json 声明的
                 sessionStart 技能渲染成 <plugin_session_start> 注入）
Superpowers 对应：hooks/session-start + docs/porting-to-a-new-harness.md 原话：
                "The bootstrap is the entire integration. Without it,
                 the skill files are inert."

职责：会话开始时，把 using-superpowers（技能总开关）注入系统提示词。
      注入内容 = <EXTREMELY_IMPORTANT> 包裹的 SKILL.md 全文。

关键设计（来自 Kimi Code 源码，蒸馏后保留）：
  1. injected_at 标记：只注入一次，避免每轮重复注入刷屏
  2. 会话恢复检测：消息列表里已有注入标记 → 跳过
     （对应 PluginSessionStartInjector 查 history 的 replayedAt 逻辑）
  3. 注入物带 variant 标记：可被识别、可被清理
"""

from __future__ import annotations

from typing import List, Optional

from skill_registry import SkillRegistry

# 注入变体标记（对应 kimi 的 injectionVariant = 'plugin_session_start'）
VARIANT = "plugin_session_start"
# 总开关技能名（bootstrap 就是它）
BOOTSTRAP_SKILL = "using-superpowers"

# 包装模板：<EXTREMELY_IMPORTANT> 是 superpowers 原版的强制语气
WRAP = (
    "<EXTREMELY_IMPORTANT>\n"
    "You have superpowers.\n"
    "\n"
    "Below is the full content of your 'superpowers:using-superpowers' "
    "skill — your introduction to using skills. "
    "For all other skills, use the load_skill tool:\n"
    "\n"
    "{content}\n"
    "</EXTREMELY_IMPORTANT>"
)


class BootstrapInjector:
    """启动注入器：生成技能总开关文本，保证每会话只注入一次。

    Args:
        registry: 技能注册表（用于定位 using-superpowers）
    """

    def __init__(self, registry: SkillRegistry):
        self.registry = registry
        self.injected_at: Optional[int] = None

    # ── 主入口 ────────────────────────────────────────────────────────────

    def build(self, existing_messages: Optional[List[dict]] = None) -> str:
        """生成 bootstrap 文本；已注入过则返回空串。

        对应 kimi PluginSessionStartInjector.getInjection()：
          已注入（injected_at 非空）→ 不重复
          消息列表里已有注入标记（replayedAt）→ 不重复
        否则返回 <EXTREMELY_IMPORTANT> 包裹的 using-superpowers 全文。
        """
        if self.injected_at is not None:
            return ""
        if self._already_injected(existing_messages):
            return ""
        content = self.registry.load(BOOTSTRAP_SKILL)
        if content is None:
            return ""
        return WRAP.format(content=content)

    def mark_injected(self, index: int) -> None:
        """注入完成后记录位置（由 TurnContext/循环在放置文本后调用）。"""
        self.injected_at = index

    @staticmethod
    def _already_injected(messages: Optional[List[dict]]) -> bool:
        """检测消息列表里是否已有注入标记（会话恢复场景）。

        对应 kimi plugin-session-start.ts:52-56 的 replayedAt 查找：
        在 history 里找 origin.kind === 'injection' 的消息。
        """
        if not messages:
            return False
        for m in messages:
            origin = m.get("origin") or {}
            if origin.get("kind") == "injection" and origin.get("variant") == VARIANT:
                return True
        return False

    # ── 生命周期重置（对应 DynamicInjector 的三个回调）────────────────────

    def on_context_clear(self) -> None:
        """上下文被清空后允许重新注入。"""
        self.injected_at = None

    def on_context_compacted(self) -> None:
        """上下文被压缩后允许重新注入——压缩可能把注入内容摘要掉。"""
        self.injected_at = None

    def on_message_removed(self, index: int) -> None:
        """消息被删除后维护 injected_at 索引（对应 kimi 的同名方法）。"""
        if self.injected_at is None:
            return
        if index < self.injected_at:
            self.injected_at -= 1
        elif index == self.injected_at:
            self.injected_at = None

#!/usr/bin/env python3
"""
turn_context.py — 模块 5/5：回合上下文准备（TurnContext）
============================================================

Hermes 对应: agent/turn_context.py 的 build_turn_context()
             + agent/prompt_builder.py（系统提示词构建）

职责：一次对话回合开始前的"一次性准备"——
  - 构建系统提示词（注入工具描述）
  - 组装初始 messages（system + user）
  - 清洗/规范化用户消息
  - 预检 API 凭证

教学要点：
  这个模块回答"Hermes 在 while 循环开始前做了什么"。
  走读卡 3 提到 run_conversation 的 prologue（conversation_loop.py:641 build_turn_context），
  就是这里的对应物——循环只负责"反复跑"，准备只做一次。
"""

from __future__ import annotations

from typing import Any


def build_system_prompt(tool_schemas: list[dict], personality: str = "", skills_index: str = "") -> str:
    """构建系统提示词，注入当前注册的工具描述 + 技能索引。

    Hermes 对应: agent/prompt_builder.py — 动态注入工具定义 + skills + 记忆。
    教学版原版只注入工具列表（skills_index 默认为空）；
    传入技能索引时，追加 <available_skills> 块——这就是"技能框架挂载点"：
    让模型知道有哪些技能、什么场景该加载哪个（渐进式披露，全文按需加载）。
    """
    if not tool_schemas:
        tool_summary = "（当前没有可用工具）"
    else:
        lines = []
        for t in tool_schemas:
            name = t.get("function", {}).get("name", "?")
            desc = t.get("function", {}).get("description", "")
            lines.append(f"- {name}: {desc}")
        tool_summary = "\n".join(lines)

    base = f"""你是 MinimalAgent Agent V2，一个可以调用工具帮助用户完成任务的 AI 助手。

你有以下工具可用：
{tool_summary}

使用规则：
1. 需要执行操作时，用 tool_calls 调用合适的工具
2. 工具返回结果后，根据结果继续推理或给出最终答案
3. 如果一次需要多个独立操作，可以同时调用多个工具
4. 用中文回复用户"""

    if skills_index:
        base += f"\n\n{skills_index}"
    if personality:
        base += f"\n\n{personality}"
    return base


def build_initial_messages(
    user_message: str,
    tool_schemas: list[dict],
    system_prompt_override: str | None = None,
    personality: str = "",
    skill_bootstrap: str = "",
    skills_index: str = "",
) -> list[dict]:
    """组装回合初始 messages：system + user。

    Hermes 对应: build_turn_context() 返回的 ctx.messages。
    教学版原版固定两段（system + user）；挂载技能框架时：
      - skills_index:   技能索引（<available_skills> 块）拼进系统提示词
      - skill_bootstrap:"技能总开关"全文拼进系统提示词（Superpowers 式启动注入）
    """
    system_prompt = system_prompt_override or build_system_prompt(tool_schemas, personality, skills_index)
    if skill_bootstrap:
        system_prompt = system_prompt + "\n\n" + skill_bootstrap
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]


def sanitize_user_message(message: Any) -> str:
    """清洗用户消息：保证是纯文本字符串。

    Hermes 对应: sanitize_surrogates + 多模态内容折叠。
    教学版只处理最基本的 str/list 情况——真实 Hermes 还会处理
    图片、孤立代理字符（surrogate）、超长截断等。
    """
    if isinstance(message, str):
        return message
    if isinstance(message, list):
        # 多模态 content parts：取所有 text 部分拼接
        parts = []
        for p in message:
            if isinstance(p, dict) and p.get("type") == "text":
                parts.append(str(p.get("text", "")))
            elif isinstance(p, str):
                parts.append(p)
        return "\n".join(parts)
    return str(message)


def check_credentials(api_key: str, base_url: str) -> tuple[bool, str]:
    """预检 API 凭证。返回 (是否可用, 错误信息)。

    Hermes 对应: _ensure_runtime_credentials() — 检查 + 自动轮换 key。
    教学版只做存在性检查，不做轮换。
    """
    if not api_key:
        return False, "缺少 API key（设置 DEEPSEEK_API_KEY 或 OPENAI_API_KEY）"
    if not base_url:
        return False, "缺少 base_url"
    return True, ""

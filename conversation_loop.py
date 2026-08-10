#!/usr/bin/env python3
"""
conversation_loop.py — 核心骨架：ConversationLoop
====================================================

Hermes 对应: agent/conversation_loop.py 的 run_conversation()
            （588~5781 行，共 5194 行）

这是 MinimalAgentV2 的"窄腰"——所有入口最终都汇聚到这里。
本文件刻意保持**骨架级精简**：所有防御逻辑被拆到 5 个模块里，
循环本身只剩"决策 + 编排"，不直接碰任何细节。

  模块对照表：
    TurnContext      → 回合准备（本骨架 run() 开头调用一次）
    LoopController   → 还继续吗？（while 条件）
    LLMClient        → 发请求 + 重试 + 错误分类（complete 一行搞定）
    ToolRunner       → 执行工具 + 结果回填
    MessageStore     → 消息增删改查 + 压缩

设计原则（对应 Hermes AGENTS.md 的 "narrow waist"）：
  骨架不增删逻辑，只做编排；具体策略全部委托给模块。
  未来若要换实现（LangGraph / 并发工具 / 流式），改模块，不动骨架。
"""

from __future__ import annotations

from typing import Any, Optional

from bootstrap_injector import BootstrapInjector
from llm_client import LLMClient, LLMError, normalize_assistant_message
from loop_controller import LoopController
from message_store import MessageStore
from skill_registry import SkillRegistry
from tool_runner import ToolRunner
from turn_context import build_initial_messages, sanitize_user_message


class ConversationLoop:
    """核心循环骨架。一次 run() = 一个完整回合（可能多轮工具调用）。

    Args:
        llm: 模型客户端
        tools: 工具执行器
        controller: 循环控制器（轮数/预算/中断）
        skills: 技能注册表（技能框架挂载点；None = 不启用技能框架）
        max_context_tokens: 触发压缩的 token 阈值
        verbose: 打印详细调试信息
    """

    def __init__(
        self,
        llm: LLMClient,
        tools: ToolRunner,
        controller: Optional[LoopController] = None,
        skills: Optional[SkillRegistry] = None,
        max_context_tokens: int = 8000,
        verbose: bool = False,
    ):
        self.llm = llm
        self.tools = tools
        self.controller = controller or LoopController(max_turns=10, verbose=verbose)
        self.skills = skills
        # 技能框架：bootstrap 注入器（会话开始注入"技能总开关"，只一次）
        self.injector = BootstrapInjector(skills) if skills is not None else None
        self.max_context_tokens = max_context_tokens
        self.verbose = verbose
        self.stats = {"api_calls": 0, "tool_calls": 0, "compressions": 0}

    # ── 对外唯一入口 ────────────────────────────────────────────────────

    def run(
        self,
        user_message: Any,
        system_prompt: Optional[str] = None,
        initial_messages: Optional[list[dict]] = None,
    ) -> dict:
        """执行一个完整回合。

        Args:
            user_message: 用户输入（str 或多模态 parts 列表）
            system_prompt: 覆盖默认系统提示词（可选）
            initial_messages: 初始消息列表（用于恢复 session）

        Returns:
            {"final_response": str, "messages": [...], "api_calls": int,
             "tool_calls": int, "exit_reason": str, "error": str|None}
        """
        # ── 回合准备（只做一次）───────────────────────────────────────
        if initial_messages is not None:
            # 恢复 session：追加用户消息
            messages = MessageStore(list(initial_messages))  # 拷贝避免修改原数据
            messages.append({"role": "user", "content": sanitize_user_message(user_message)})
        else:
            clean_message = sanitize_user_message(user_message)
            # 技能框架注入（对应 kimi 回合循环里的 DynamicInjector.inject()）：
            #   bootstrap = "技能总开关"全文（已注入过则返回空串，只注入一次）
            #   index     = 技能索引列表（Hermes 式 <available_skills> 块）
            skill_bootstrap = self.injector.build() if self.injector else ""
            skills_index = self.skills.index_text() if self.skills else ""
            messages = MessageStore(
                build_initial_messages(
                    clean_message,
                    self.tools.schemas(),
                    system_prompt_override=system_prompt,
                    skill_bootstrap=skill_bootstrap,
                    skills_index=skills_index,
                )
            )
            # 注入标记：system 消息带 origin（会话恢复时据此跳过重复注入）
            if skill_bootstrap and self.injector is not None:
                system_msg = messages.all()[0]
                system_msg["origin"] = {"kind": "injection", "variant": "plugin_session_start"}
                self.injector.mark_injected(0)
        self.controller.reset()

        # ── 核心循环（骨架）───────────────────────────────────────────
        while self.controller.should_continue():
            self.controller.record_turn()

            # 1. 发请求（重试/错误分类在 LLMClient 内部）
            try:
                response = self.llm.complete(
                    messages.all(),
                    tools=self.tools.schemas(),
                )
            except LLMError as e:
                return self._error_result(messages, e)

            self.stats["api_calls"] += 1
            assistant = normalize_assistant_message(response.choices[0].message)

            # 2. 有工具调用 → 执行 → 回填 → 继续
            if assistant.get("tool_calls"):
                messages.append_assistant_with_tool_calls(assistant)
                results = self.tools.execute_all(assistant["tool_calls"])
                for r in results:
                    messages.append(r)
                self.stats["tool_calls"] += len(results)

                # 3. 超长压缩（MessageStore 内部处理）
                if messages.compress_if_needed(self.max_context_tokens):
                    self.stats["compressions"] += 1
                continue

            # 4. 没有工具调用 → 最终回答
            return self._success_result(messages, assistant)

        # 循环退出（预算/上限/中断）
        return self._timeout_result(messages)

    # ── 结果组装 ────────────────────────────────────────────────────────

    def _success_result(self, messages: MessageStore, assistant: dict) -> dict:
        return {
            "final_response": assistant.get("content") or "",
            "messages": messages.snapshot(),
            "api_calls": self.stats["api_calls"],
            "tool_calls": self.stats["tool_calls"],
            "exit_reason": "completed",
            "error": None,
        }

    def _timeout_result(self, messages: MessageStore) -> dict:
        reason = self.controller.exit_reason() or "max_turns_reached"
        return {
            "final_response": f"(达到上限：{reason}，未获得最终回复)",
            "messages": messages.snapshot(),
            "api_calls": self.stats["api_calls"],
            "tool_calls": self.stats["tool_calls"],
            "exit_reason": reason,
            "error": reason,
        }

    def _error_result(self, messages: MessageStore, err: LLMError) -> dict:
        return {
            "final_response": f"⚠️ {err}",
            "messages": messages.snapshot(),
            "api_calls": self.stats["api_calls"],
            "tool_calls": self.stats["tool_calls"],
            "exit_reason": f"error:{err.category}",
            "error": str(err),
        }

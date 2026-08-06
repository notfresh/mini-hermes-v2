#!/usr/bin/env python3
"""
cli.py — MinimalAgentV2 命令行入口
====================================

Hermes 对应: cli.py main()（入口 → 组装 → 跑核心循环）

传承自 MinimalAgentV1 main()：
  - --provider deepseek/openai 快捷选择
  - --base-url 覆盖
  - --max-turns 循环上限
  - --verbose 调试输出
  - --list-tools 工具清单
"""

from __future__ import annotations

import argparse
import os
import sys

from conversation_loop import ConversationLoop
from llm_client import LLMClient
from loop_controller import LoopController
import tools  # noqa: F401  # import 即触发 @tool 注册
from tool_runner import ToolRunner, _TOOL_SCHEMAS


def _resolve_api_key(base_url: str) -> str:
    """从环境变量找 API key（传承 V1）。"""
    if "deepseek" in base_url.lower():
        return os.environ.get("DEEPSEEK_API_KEY", "")
    return os.environ.get("OPENAI_API_KEY", "")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MinimalAgentV2 — 五模块拆分的教学级 Agent 框架",
    )
    parser.add_argument("message", nargs="?", help="用户消息")
    parser.add_argument("--model", default="deepseek-chat",
                        help="模型名 (默认: deepseek-chat)")
    parser.add_argument("--provider", choices=["deepseek", "openai"],
                        default="deepseek",
                        help="快捷选择 API endpoint")
    parser.add_argument("--base-url", default="",
                        help="API base URL (覆盖 --provider)")
    parser.add_argument("--max-turns", type=int, default=10,
                        help="最大工具调用轮次 (默认: 10)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="打印详细调试信息")
    parser.add_argument("--list-tools", action="store_true",
                        help="列出已注册的工具")
    parser.add_argument("--personality", default="",
                        help="追加到系统提示词的性格/约束描述")
    return parser


def main() -> None:
    args = _build_parser().parse_args()

    # ── 解析 provider ──
    base_url = args.base_url or {
        "deepseek": "https://api.deepseek.com/v1",
        "openai": "https://api.openai.com/v1",
    }[args.provider]

    # ── 仅列出工具 ──
    if args.list_tools:
        print(f"已注册 {len(_TOOL_SCHEMAS)} 个工具:")
        tools.list_tools()
        return

    # ── API key ──
    api_key = _resolve_api_key(base_url)
    if not api_key:
        print("❌ 需要设置 API key")
        print("   export DEEPSEEK_API_KEY=sk-xxx   # DeepSeek")
        print("   export OPENAI_API_KEY=sk-xxx     # OpenAI")
        sys.exit(1)

    # ── 消息 ──
    message = args.message
    if not message:
        try:
            message = input("💬 你的消息: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)
    if not message:
        print("啥也没说。88")
        return

    # ── 组装五模块 ──
    tools_runner = ToolRunner(verbose=args.verbose)
    llm = LLMClient(
        model=args.model,
        base_url=base_url,
        api_key=api_key,
        verbose=args.verbose,
    )
    controller = LoopController(max_turns=args.max_turns, verbose=args.verbose)
    loop = ConversationLoop(
        llm=llm,
        tools=tools_runner,
        controller=controller,
        verbose=args.verbose,
    )

    if args.verbose:
        print(f"\n{'='*60}")
        print(f"🤖  Model: {args.model} @ {base_url}")
        print(f"📦  Tools: {len(tools_runner.schemas())}")
        print(f"🎛  模块: TurnContext / LoopController / LLMClient / ToolRunner / MessageStore")
        print(f"💬  User: {message[:200]}")
        print(f"{'─'*60}")

    # ── 跑核心循环 ──
    result = loop.run(message, system_prompt=None)

    print(f"\n{'='*60}")
    print(result["final_response"])
    if args.verbose:
        print(f"\n📊 统计: {result['api_calls']} 次 API / {result['tool_calls']} 次工具 / "
              f"退出原因: {result['exit_reason']}")


if __name__ == "__main__":
    main()

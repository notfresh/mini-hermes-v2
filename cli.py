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
from pathlib import Path

from conversation_loop import ConversationLoop
from llm_client import LLMClient
from loop_controller import LoopController
from agent_ignore import AgentIgnore
import config  # noqa: F401  # 配置文件加载
import tools  # noqa: F401  # import 即触发 @tool 注册
import plan_mode  # noqa: F401  # Plan Mode：注册 enter/exit_plan_mode 工具
from plan_mode import plan_guard  # 守卫：规划模式激活时限制 write
from tool_runner import ToolRunner, _TOOL_SCHEMAS
from skill_registry import SkillRegistry


def _resolve_api_key(base_url: str) -> str:
    """从环境变量找 API key（传承 V1）；找不到再读 Hermes 配置。

    技能框架挂载版补充：用户环境未 export key 时，复用
    ~/.hermes/config.json 里 Hermes 正在用的 key（openai.api_key，
    base_url 为 api.deepseek.com/v1 即 DeepSeek）。
    """
    if "deepseek" in base_url.lower():
        key = os.environ.get("DEEPSEEK_API_KEY", "")
        if key:
            return key
    else:
        key = os.environ.get("OPENAI_API_KEY", "")
        if key:
            return key
    # 兜底：读 Hermes 配置
    hermes_cfg = os.path.expanduser("~/.hermes/config.json")
    if os.path.isfile(hermes_cfg):
        try:
            import json
            cfg = json.loads(open(hermes_cfg).read())
            return cfg.get("openai", {}).get("api_key", "")
        except Exception:
            pass
    return ""


def _build_parser(defaults: dict = None) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="MinimalAgentV2 — 五模块拆分的教学级 Agent 框架",
    )
    # 配置文件参数（最早解析，用于获取默认配置）
    parser.add_argument("--config", type=str, default="",
                        help="指定配置文件路径（默认: 查找项目/.minimal-agent-v2.toml 或 ~/.minimal-agent-v2/config.toml）")

    # 解析配置文件获取默认值
    cfg = defaults or {}

    parser.add_argument("message", nargs="?", help="用户消息")
    parser.add_argument("--model", default=cfg.get("model", "deepseek-chat"),
                        help="模型名 (默认: deepseek-chat)")
    parser.add_argument("--provider", choices=["deepseek", "openai"],
                        default=cfg.get("provider", "deepseek"),
                        help="快捷选择 API endpoint")
    parser.add_argument("--base-url", default="",
                        help="API base URL (覆盖 --provider)")
    parser.add_argument("--max-turns", type=int, default=cfg.get("max_turns", 10),
                        help="最大工具调用轮次")
    parser.add_argument("--verbose", "-v", action="store_true",
                        default=cfg.get("verbose", False),
                        help="打印详细调试信息")
    parser.add_argument("--list-tools", action="store_true",
                        help="列出已注册的工具")
    parser.add_argument("--personality", default="",
                        help="追加到系统提示词的性格/约束描述")
    parser.add_argument("--no-skills", action="store_true",
                        help="禁用技能框架（回到无技能的 V2 原版行为）")
    parser.add_argument("--skills-dir", default=cfg.get("skills_dir", ""),
                        help="挂载外部技能包目录")
    parser.add_argument("-i", "--interactive", action="store_true",
                        help="交互模式（REPL）")
    return parser


def _print_skills(skills: SkillRegistry) -> None:
    """打印已挂载的技能清单（技能框架模式启动时显示）。"""
    print(f"\n🧠 技能框架已挂载 ({len(skills.list_skills())} 个技能):")
    for s in skills.list_skills():
        desc = (s["description"] or "")[:60]
        print(f"   · {s['name']:<28} {desc}")
    print(f"{'─'*60}")


def main() -> None:
    # ── plugin 子命令早期 dispatch（不走 _build_parser，避免影响主对话流程）──
    if len(sys.argv) >= 2 and sys.argv[1] == "plugin":
        import plugin_manager
        plugin_manager._run_plugin_command(sys.argv[2:])
        return

    # 从命令行直接获取 --config 参数（避免解析顺序问题）
    config_path = None
    for i, arg in enumerate(sys.argv):
        if arg == "--config" and i + 1 < len(sys.argv):
            config_path = sys.argv[i + 1]
            break

    # 加载配置
    if config_path:
        cfg = config.load_config(config_path=Path(config_path))
    else:
        cfg = config.load_config()

    # 用配置作为默认值构建完整解析器
    args = _build_parser(defaults=cfg).parse_args()

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

    # ── 交互模式 ─────────────────────────────────────────────────────
    if args.interactive:
        from session_manager import run_repl
        tools_runner = ToolRunner(verbose=args.verbose)
        # AgentIgnore：路径级权限校验（当前工作目录下的 .agentignore，无文件则不启用）
        tools_runner.agent_ignore = AgentIgnore.load_default()
        tools_runner.guard = plan_guard  # Plan Mode V2：注入守卫（硬约束）
        llm = LLMClient(
            model=args.model,
            base_url=base_url,
            api_key=api_key,
            verbose=args.verbose,
        )
        # 技能框架挂载：--skills-dir 指向外部技能包（如 minimal-superpowers）TODO 待清除
        skills = None if (args.no_skills or not args.skills_dir) else SkillRegistry(args.skills_dir)
        if skills is not None:
            tools.set_registry(skills)
            _print_skills(skills)
            
        run_repl(
            tools_runner=tools_runner,
            llm=llm,
            verbose=args.verbose,
            max_turns=args.max_turns,
            skills=skills,
        )
        return

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
    # AgentIgnore：路径级权限校验（当前工作目录下的 .agentignore，无文件则不启用）
    tools_runner.agent_ignore = AgentIgnore.load_default()
    tools_runner.guard = plan_guard  # Plan Mode V2：注入守卫（硬约束）
    llm = LLMClient(
        model=args.model,
        base_url=base_url,
        api_key=api_key,
        verbose=args.verbose,
    )
    controller = LoopController(max_turns=args.max_turns, verbose=args.verbose)
    # 技能框架挂载：--skills-dir 指向外部技能包（如 minimal-superpowers）
    skills = None if (args.no_skills or not args.skills_dir) else SkillRegistry(args.skills_dir)
    if skills is not None:
        tools.set_registry(skills)
        _print_skills(skills)
    loop = ConversationLoop(
        llm=llm,
        tools=tools_runner,
        controller=controller,
        skills=skills,
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

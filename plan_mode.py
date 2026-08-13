#!/usr/bin/env python3
"""
plan_mode.py — Plan Mode V1：纯提示词规划（软约束）
=====================================================

Hermes 对应: software-development/plan skill（plan mode：写计划文档，只计划不执行）
Kimi Code 对应: EnterPlanMode 工具的文本引导（enter-plan-mode.md）

第一版 = 软方案：无状态机、无守卫。
约束全部来自提示词（工具 description + system prompt 引导），
可靠性依赖模型自觉——这是理解"软约束边界"的铺垫版，
也是 V2 后续加硬守卫（Plan Mode V2：状态机 + guard）的基础。

V1 增强点（用户要求）：
  1. 每个阶段必须写明"验收条件"——可执行、可验证的完成标准
  2. 完成时做验证——阶段验证（每步完成后对照验收条件）+ 整体验证（全部完成后逐条核对）
"""

from __future__ import annotations

import datetime
import pathlib

from tool_runner import tool

# 计划文件目录：~/.minimal-agent-v2/plans/
PLANS_DIR = pathlib.Path.home() / ".minimal-agent-v2" / "plans"

# 规划引导全文（工具 description = 模型看到的完整规则）
PLAN_GUIDANCE = """把当前任务拆解为分阶段计划，写入计划文件，然后按计划执行。

适用场景：多步骤 / 多文件 / 需要设计决策的复杂任务。
不适用：单行修复、纯查询、用户已给出明确详细步骤的任务。

计划文件格式（markdown）：
# 任务计划：<任务名>
## 阶段 1：<阶段名>
- 目标：<这一步要达成什么>
- 验收条件：<可执行、可验证的完成标准——能明确判断"这一步算完成"，
  例如"xxx.py 已创建且 import 不报错"、"输出结果包含 key 字段">
## 阶段 2：<阶段名>
- 目标：...
- 验收条件：...
（阶段数量按任务复杂度自定）

执行规则（必须遵守）：
1. 接到复杂任务，先调用本工具写好计划，再开始执行
2. 每个阶段必须同时给出"目标"和"验收条件"，缺一不可
3. 每完成一个阶段，先对照该阶段的验收条件验证结果；
   不满足则修正后重新验证，满足才进入下一阶段
4. 所有阶段完成后，做整体验证：逐条核对全部验收条件，
   全部满足才向用户报告完成；有未满足的，说明原因并继续修正"""


@tool(description=PLAN_GUIDANCE)
def plan(content: str) -> str:
    """把任务拆解为分阶段计划并写入计划文件，之后按计划执行。

    Args:
        content: 计划全文（markdown），每个阶段包含目标 + 验收条件
    """
    PLANS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = PLANS_DIR / f"plan-{ts}.md"
    path.write_text(content, encoding="utf-8")
    return (
        f"计划已写入 {path}。现在按计划执行：每完成一个阶段，"
        "对照该阶段的验收条件验证；全部完成后做整体验证，逐条核对所有验收条件。"
    )

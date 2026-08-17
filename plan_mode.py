#!/usr/bin/env python3
"""
plan_mode.py — Plan Mode V2：状态机 + 守卫（硬约束）
=====================================================

从 V1（纯提示词规划）演进：V1 靠模型自觉遵守"先规划"；
V2 把"规划"变成**有状态、被强制**的阶段——

  V1: plan 工具（模型想用就用，写计划文件）
  V2: enter_plan_mode →（规划中：只能读 + 写计划文件）→ exit_plan_mode → 执行

Kimi Code 对应:
  - PlanMode 类        → packages/agent-core/src/agent/plan/index.ts
  - enter/exit 工具    → tools/builtin/planning/enter-plan-mode.ts + exit-plan-mode.ts
  - plan_guard（守卫） → permission/policies/plan-mode-guard-deny.ts（deny 拦截）

核心教学点（"谁在强制"）：
  - 状态在框架代码里（plan_mode.is_active），不在模型上下文里——模型无法"忘记"
  - 每次工具调用先过守卫（tool_runner.execute 的 guard 检查点），违规返回 DENIED，
    工具不执行——这就是软（V1 提示词）和硬（V2 守卫）的分界线。
"""

from __future__ import annotations

import datetime
import pathlib
from typing import Optional

from tool_runner import tool

# 计划文件目录：~/.minimal-agent-v2/plans/
PLANS_DIR = pathlib.Path.home() / ".minimal-agent-v2" / "plans"


class PlanMode:
    """规划模式状态机（镜像 Kimi PlanMode）。

    状态存在框架内存里：is_active / plan_path。
    进入时创建空计划文件；退出时清空状态。
    """

    def __init__(self, plans_dir: pathlib.Path = PLANS_DIR):
        self._active = False
        self._plan_id: Optional[str] = None
        self._plan_path: Optional[pathlib.Path] = None
        self._plans_dir = plans_dir

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def plan_path(self) -> Optional[pathlib.Path]:
        return self._plan_path

    def enter(self) -> pathlib.Path:
        """进入规划模式：创建空计划文件，返回其路径。"""
        if self._active:
            raise RuntimeError("已在规划模式中，先 exit_plan_mode 再进入")
        self._plans_dir.mkdir(parents=True, exist_ok=True)
        self._plan_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        self._plan_path = self._plans_dir / f"plan-{self._plan_id}.md"
        self._plan_path.write_text("", encoding="utf-8")
        self._active = True
        return self._plan_path

    def exit(self) -> None:
        """退出规划模式：清空状态。"""
        self._active = False
        self._plan_id = None
        self._plan_path = None


# 模块级单例（教学版简化；真实 Hermes/Kimi 挂在 agent 实例上）
plan_mode = PlanMode()


def plan_guard(name: str, args: dict) -> Optional[str]:
    """守卫（Kimi plan-mode-guard-deny 的 Python 版）。

    规划模式激活时：write 只能写计划文件，其他一律拒绝。
    返回 None 表示放行；返回字符串表示拒绝原因（工具不执行）。

    说明：bash 不拦截（Kimi 同样："Bash follows the normal permission mode"）——
    这是教学版的已知简化边界，bash 可绕守卫，真实系统会在 shell 层补防。
    """
    if plan_mode.is_active and name == "write":
        target = str(args.get("path", ""))
        if target != str(plan_mode.plan_path):
            return (
                f"规划模式激活中：只允许写入计划文件 {plan_mode.plan_path}，"
                f"目标 {target} 被守卫拒绝。"
                "如需修改其他文件，先调用 exit_plan_mode 退出规划模式。"
            )
    return None


# ── 规划模式工具（进入/退出）──────────────────────────────────────────────

ENTER_GUIDANCE = """进入规划模式。适用于：多步骤 / 多文件 / 需要设计决策的复杂任务——先拆解计划、获得认可，再开始执行。
不适用：单行修复、纯查询、用户已给出明确详细步骤的任务。

进入后工作流：
1. 用只读工具（read / ls / grep / find）调研当前情况
2. 用 write 工具把计划写入计划文件（路径由系统返回），格式：
   # 任务计划：<任务名>
   ## 阶段 1：<阶段名>
   - 目标：<这一步要达成什么>
   - 验收条件：<可执行、可验证的完成标准，能明确判断"这一步算完成">
3. 规划模式下只能写入计划文件——写其他文件会被守卫拒绝
4. 计划写好后，调用 exit_plan_mode 退出规划模式、开始执行"""


@tool(description=ENTER_GUIDANCE)
def enter_plan_mode() -> str:
    """进入规划模式：创建计划文件，之后只能读 + 写计划文件。

    Returns:
        计划文件路径 + 工作流提示
    """
    if plan_mode.is_active:
        return f"已在规划模式中，计划文件：{plan_mode.plan_path}。用 write 更新计划，写好后调 exit_plan_mode。"
    path = plan_mode.enter()
    return (
        f"已进入规划模式。计划文件：{path}。"
        "工作流：只读调研 → write 写入计划（每个阶段含目标 + 验收条件）→ exit_plan_mode 开始执行。"
    )


EXIT_GUIDANCE = """退出规划模式，开始执行已批准的计划。
调用前确保计划已用 write 写入计划文件；退出后所有工具恢复可用。
执行规则：
1. 每完成一个阶段，先对照该阶段的验收条件验证结果；不满足则修正后重新验证
2. 全部阶段完成后，做整体验证：逐条核对所有验收条件，全部满足才向用户报告完成"""


@tool(description=EXIT_GUIDANCE)
def exit_plan_mode() -> str:
    """退出规划模式：解除写限制，开始按计划执行。

    Returns:
        退出确认
    """
    if not plan_mode.is_active:
        return "当前不在规划模式。"
    plan_mode.exit()
    return (
        "已退出规划模式，所有工具恢复可用。"
        "按计划执行：每完成一个阶段对照验收条件验证；全部完成后做整体验证。"
    )

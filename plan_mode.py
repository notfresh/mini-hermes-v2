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

    状态存在框架内存里：status / plan_path。
    V3 新增审批状态：idle → planning → awaiting_approval → approved，
    审批不再是提示词软约束，而是框架硬状态——exit_plan_mode 必须 approved 才放行。

    状态迁移：
      enter()            → planning（创建空计划文件）
      write_plan()       → awaiting_approval（计划已提交，等用户审批）
      approve()          → approved（用户 /approve 批准）
      revise()           → planning（用户 /revise，要求重写后重新提交）
      cancel() / exit()  → idle（清空状态）
    """

    # 状态常量
    STATUS_IDLE = "idle"
    STATUS_PLANNING = "planning"
    STATUS_AWAITING = "awaiting_approval"
    STATUS_APPROVED = "approved"

    _STATUS_LABELS = {
        STATUS_IDLE: "未激活",
        STATUS_PLANNING: "规划中",
        STATUS_AWAITING: "待审批",
        STATUS_APPROVED: "已批准",
    }

    def __init__(self, plans_dir: pathlib.Path = PLANS_DIR):
        self._status = self.STATUS_IDLE
        self._plan_id: Optional[str] = None
        self._plan_path: Optional[pathlib.Path] = None
        self._plans_dir = plans_dir

    @property
    def is_active(self) -> bool:
        return self._status != self.STATUS_IDLE

    @property
    def status(self) -> str:
        return self._status

    @property
    def status_label(self) -> str:
        """中文状态标签（REPL banner / 状态注入用）。"""
        return self._STATUS_LABELS.get(self._status, self._status)

    @property
    def plan_path(self) -> Optional[pathlib.Path]:
        return self._plan_path

    def enter(self) -> pathlib.Path:
        """进入规划模式：创建空计划文件，返回其路径。"""
        if self.is_active:
            raise RuntimeError("已在规划模式中，先 exit_plan_mode 再进入")
        self._plans_dir.mkdir(parents=True, exist_ok=True)
        self._plan_id = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        self._plan_path = self._plans_dir / f"plan-{self._plan_id}.md"
        self._plan_path.write_text("", encoding="utf-8")
        self._status = self.STATUS_PLANNING
        return self._plan_path

    def approve(self) -> None:
        """用户批准计划（/approve）。仅 awaiting_approval 可批准。"""
        if not self.is_active:
            raise RuntimeError("当前不在规划模式，无法批准")
        if self._status != self.STATUS_AWAITING:
            raise RuntimeError(
                f"当前状态为 {self.status_label}，只有计划提交（待审批）后才能批准"
            )
        self._status = self.STATUS_APPROVED

    def revise(self) -> None:
        """用户要求修改计划（/revise）：状态打回 planning，必须重写后重新提交。"""
        if not self.is_active:
            raise RuntimeError("当前不在规划模式，无法修订")
        self._status = self.STATUS_PLANNING

    def submit(self) -> None:
        """计划已写入 → 置为待审批（write_plan 专用，模型提交计划后调用）。"""
        if not self.is_active:
            raise RuntimeError("当前不在规划模式，无法提交计划")
        self._status = self.STATUS_AWAITING

    def cancel(self) -> None:
        """取消计划（/cancel）：清空状态，计划文件保留（审计）。"""
        self._reset()

    def exit(self) -> None:
        """退出规划模式：清空状态。"""
        self._reset()

    def _reset(self) -> None:
        self._status = self.STATUS_IDLE
        self._plan_id = None
        self._plan_path = None


# 模块级单例（教学版简化；真实 Hermes/Kimi 挂在 agent 实例上）
plan_mode = PlanMode()


def plan_guard(name: str, args: dict) -> Optional[str]:
    """守卫（Kimi plan-mode-guard-deny 的 Python 版）。

    规划模式激活时：
      - write：只能写计划文件，其他一律拒绝（现状不变）
      - exit_plan_mode：必须 approved 才放行——模型未获用户批准不能退出规划模式
    返回 None 表示放行；返回字符串表示拒绝原因（工具不执行）。

    说明：bash 不拦截（Kimi 同样："Bash follows the normal permission mode"）——
    这是教学版的已知简化边界，bash 可绕守卫，真实系统会在 shell 层补防。
    """
    if not plan_mode.is_active:
        return None

    # 拦截 1：规划期写非计划文件
    if name == "write":
        target = str(args.get("path", ""))
        if target != str(plan_mode.plan_path):
            return (
                f"规划模式激活中：只允许写入计划文件 {plan_mode.plan_path}，"
                f"目标 {target} 被守卫拒绝。"
                "如需修改其他文件，先调用 exit_plan_mode 退出规划模式。"
            )

    # 拦截 2：未获批准不得退出规划模式（V3 审批硬闭环的核心）
    if name == "exit_plan_mode":
        if plan_mode.status != plan_mode.STATUS_APPROVED:
            return (
                f"计划尚未获用户批准（当前状态：{plan_mode.status_label}）。"
                "必须等用户输入 /approve 批准后才能退出规划模式。"
                "若用户要求修改，输入 /revise <反馈>；若取消，输入 /cancel。"
            )
    return None


# ── 规划模式工具（进入/退出）──────────────────────────────────────────────

ENTER_GUIDANCE = """进入规划模式。适用于：多步骤 / 多文件 / 需要设计决策的复杂任务——先拆解计划、获得认可，再开始执行。
不适用：单行修复、纯查询、用户已给出明确详细步骤的任务。

进入前：评估任务是否清晰。若需求模糊（目标/范围/验收标准不明确），先用对话/AskUserQuestion
      主动向用户澄清 1-3 个关键问题。澄清后信息越清晰，调研+写计划越省力。

进入后工作流：
1. 用只读工具（read / ls / grep / find）调研当前情况
2. 调研中遇到关键设计决策不确定（库选型/接口形状/取舍），再向用户提问
3. 用 write_plan(content=...) 把完整计划写入当前计划文件（路径由框架绑定，工具会自动处理）
   计划格式：
   # 任务计划：<任务名>
   ## 阶段 1：<阶段名>
   - 目标：<这一步要达成什么>
   - 验收条件：<可执行、可验证的完成标准，能明确判断"这一步算完成">
4. 计划写好后，告知用户"等待审批"，由用户输入 /approve / /revise / /cancel 决定下一步
   - 不能主动调 exit_plan_mode 退出规划模式——必须等用户审批通过
5. 收到"✓ 计划已批准"消息后，调 exit_plan_mode 开始执行"""


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
        "工作流：调研 → write_plan 写入计划（覆盖式） → 等待用户输入 /approve / /revise / /cancel。"
        "收到\"已批准\"消息后，调 exit_plan_mode 开始执行。"
    )


WRITE_PLAN_GUIDANCE = """把计划写入当前计划文件（plan_mode 激活时专用）。

调用前提：已调 enter_plan_mode 进入规划模式。
参数 content：完整计划内容（Markdown），包含阶段标题、目标、验收条件。
语义：覆盖式写入（每次写完整版本，不做拼接）。
返回：写入结果 + 引导用户走 /approve / /revise / /cancel。

不要用通用 write 工具写计划——走这个专用工具，路径不会拼错。"""


@tool(description=WRITE_PLAN_GUIDANCE)
def write_plan(content: str) -> str:
    """把完整计划覆盖写入当前计划文件（plan_mode 激活时专用）。

    行为：
      - 未在 plan 模式：返回错误字符串（自保护，不抛异常）
      - 空 content：拒绝（防御性，避免空计划提交审批）
      - 正常：覆盖写入 plan_path
    """
    if not plan_mode.is_active or plan_mode.plan_path is None:
        return "错误：未在规划模式。请先调 enter_plan_mode。"
    if not content or not content.strip():
        return "错误：计划内容不能为空。"
    plan_mode.plan_path.write_text(content, encoding="utf-8")
    plan_mode.submit()  # 计划已提交 → 待审批
    return (
        f"已写入计划 ({len(content)} 字符, {plan_mode.plan_path})。"
        "计划已提交，等待用户审批：用户将输入 /approve (批准执行)、"
        "/revise <反馈> (修改) 或 /cancel (取消)。"
    )


EXIT_GUIDANCE = """退出规划模式，开始执行已批准的计划。
调用前确保计划已用 write_plan 写入计划文件；退出后所有工具恢复可用。
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

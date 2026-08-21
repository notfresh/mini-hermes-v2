"""plan_mode 模块测试：write_plan 工具 + PlanMode 状态机。"""
from __future__ import annotations

import pytest

from plan_mode import plan_mode, write_plan


# ── write_plan 工具 ────────────────────────────────────────────────


def test_write_plan_requires_active_mode():
    """未在 plan 模式时调用 write_plan → 返回错误字符串，文件不创建。"""
    result = write_plan(content="# 计划内容")
    assert "未在规划模式" in result


def test_write_plan_rejects_empty_content():
    """plan 模式激活但 content 为空 → 返回错误。"""
    plan_mode.enter()
    try:
        result = write_plan(content="")
        assert "不能为空" in result
        # 文件应保持初始空状态
        assert plan_mode.plan_path.read_text(encoding="utf-8") == ""
    finally:
        plan_mode.exit()


def test_write_plan_writes_content(tmp_path):
    """plan 模式激活 + 正常 content → 文件被写入，返回字符数。"""
    plan_mode.enter()
    try:
        content = "# 任务计划：CSV 解析\n## 阶段 1\n- 目标：实现解析\n- 验收：可读 sample.csv"
        result = write_plan(content=content)
        # 返回字符串包含字符数
        assert str(len(content)) in result
        # 文件内容应等于 content
        assert plan_mode.plan_path.read_text(encoding="utf-8") == content
    finally:
        plan_mode.exit()


def test_write_plan_overwrites_previous_content(tmp_path):
    """write_plan 是覆盖语义：先写 A 再写 B → 文件 = B，A 不残留。"""
    plan_mode.enter()
    try:
        write_plan(content="旧内容 A")
        write_plan(content="新内容 B")
        assert plan_mode.plan_path.read_text(encoding="utf-8") == "新内容 B"
    finally:
        plan_mode.exit()


# ── PlanMode 状态机 ────────────────────────────────────────────────


def test_plan_mode_enter_exit_toggles_is_active(tmp_path):
    """enter 后 is_active=True；exit 后 is_active=False；plan_path 同步切换。"""
    from plan_mode import PlanMode

    pm = PlanMode(plans_dir=tmp_path)
    assert pm.is_active is False
    assert pm.plan_path is None

    path = pm.enter()
    assert pm.is_active is True
    assert pm.plan_path == path
    assert path.exists()

    pm.exit()
    assert pm.is_active is False
    assert pm.plan_path is None


def test_plan_mode_double_enter_raises(tmp_path):
    """连续 enter 抛 RuntimeError。"""
    from plan_mode import PlanMode

    pm = PlanMode(plans_dir=tmp_path)
    pm.enter()
    try:
        with pytest.raises(RuntimeError):
            pm.enter()
    finally:
        pm.exit()


def test_plan_mode_exit_when_inactive_is_idempotent(tmp_path):
    """未激活时 exit 不抛异常（幂等）。"""
    from plan_mode import PlanMode

    pm = PlanMode(plans_dir=tmp_path)
    pm.exit()  # 不应抛
    assert pm.is_active is False


# ── V3 审批状态机迁移 ──────────────────────────────────────────────


def test_enter_sets_planning_status():
    """enter 后状态 = planning。"""
    plan_mode.enter()
    try:
        assert plan_mode.status == plan_mode.STATUS_PLANNING
        assert plan_mode.status_label == "规划中"
    finally:
        plan_mode.exit()


def test_write_plan_sets_awaiting_approval():
    """write_plan 后状态 = awaiting_approval（计划已提交待审批）。"""
    plan_mode.enter()
    try:
        write_plan(content="# 计划")
        assert plan_mode.status == plan_mode.STATUS_AWAITING
        assert plan_mode.status_label == "待审批"
    finally:
        plan_mode.exit()


def test_approve_requires_awaiting():
    """planning 状态 approve → RuntimeError；awaiting 状态 approve → approved。"""
    plan_mode.enter()
    try:
        with pytest.raises(RuntimeError):
            plan_mode.approve()
        write_plan(content="# 计划")
        plan_mode.approve()
        assert plan_mode.status == plan_mode.STATUS_APPROVED
        assert plan_mode.status_label == "已批准"
    finally:
        plan_mode.exit()


def test_revise_returns_to_planning():
    """/revise 后状态打回 planning；重写后重新提交 → 回到 awaiting。"""
    plan_mode.enter()
    try:
        write_plan(content="# 计划")
        plan_mode.revise()
        assert plan_mode.status == plan_mode.STATUS_PLANNING
        # 重写后再提交 → 回到待审批（每次审批的对象都是最新版本）
        write_plan(content="# 计划 v2")
        assert plan_mode.status == plan_mode.STATUS_AWAITING
    finally:
        plan_mode.exit()


def test_cancel_returns_to_idle():
    """cancel 后状态回 idle，plan_path 清空。"""
    plan_mode.enter()
    write_plan(content="# 计划")
    plan_mode.cancel()
    assert plan_mode.is_active is False
    assert plan_mode.plan_path is None


# ── V3 守卫：exit_plan_mode 审批拦截 ───────────────────────────────


def test_guard_blocks_exit_without_approval():
    """未批准时模型调 exit_plan_mode → DENIED（硬约束核心）。"""
    from plan_mode import plan_guard

    plan_mode.enter()
    try:
        write_plan(content="# 计划")
        reason = plan_guard("exit_plan_mode", {})
        assert reason is not None
        assert "尚未获用户批准" in reason
    finally:
        plan_mode.exit()


def test_guard_allows_exit_after_approval():
    """批准后 exit_plan_mode → 放行。"""
    from plan_mode import plan_guard

    plan_mode.enter()
    try:
        write_plan(content="# 计划")
        plan_mode.approve()
        assert plan_guard("exit_plan_mode", {}) is None
    finally:
        plan_mode.exit()


def test_guard_still_blocks_write_outside_plan_file():
    """规划期写非计划文件仍被拦（V2 行为不变）。"""
    from plan_mode import plan_guard

    plan_mode.enter()
    try:
        reason = plan_guard("write", {"path": "/tmp/evil.py"})
        assert reason is not None
        assert "被守卫拒绝" in reason
    finally:
        plan_mode.exit()


def test_guard_inactive_passes_everything():
    """plan 未激活：write / exit_plan_mode 都放行（不启用规划约束）。"""
    from plan_mode import plan_guard

    assert plan_guard("write", {"path": "/tmp/evil.py"}) is None
    assert plan_guard("exit_plan_mode", {}) is None
"""session_manager 测试：REPL banner + plan 审批 slash 命令辅助函数。

仅测试可独立调用的辅助函数，不直接测 run_repl（避免 mock input()）。
"""
from __future__ import annotations

import pytest

from plan_mode import plan_mode, write_plan
from session_manager import _maybe_print_plan_banner
from session_manager import _process_plan_command
from session_manager import _process_run_command
from session_manager import _process_user_input
from turn_context import plan_status_line


# ── _maybe_print_plan_banner ────────────────────────────────────────


def test_banner_prints_when_plan_active_and_file_exists(capsys, tmp_path):
    """plan 模式激活 + 文件存在 + 有内容 → 打印 banner 含内容与状态标签。"""
    plan_mode.enter()
    try:
        plan_mode.plan_path.write_text("# 测试计划\n## 阶段 1\n- 目标 X\n- 验收 Y",
                                        encoding="utf-8")
        _maybe_print_plan_banner()
        captured = capsys.readouterr()
        assert "📋 当前计划" in captured.out
        assert "规划中" in captured.out  # 状态标签
        assert "# 测试计划" in captured.out
        assert "## 阶段 1" in captured.out
    finally:
        plan_mode.exit()


def test_banner_skipped_when_plan_inactive(capsys):
    """plan 模式关闭 → 不打印。"""
    _maybe_print_plan_banner()
    captured = capsys.readouterr()
    assert captured.out == ""


def test_banner_handles_io_error_silently(capsys, monkeypatch, tmp_path):
    """读文件抛 OSError → 不抛异常，不打印，REPL 继续。"""
    plan_mode.enter()
    try:
        # 把 plan_path 指向一个 read_text 会失败的伪路径
        import pathlib
        original_read_text = pathlib.Path.read_text

        def fake_read_text(self, *args, **kwargs):
            raise OSError("模拟 IO 错误")

        monkeypatch.setattr(pathlib.Path, "read_text", fake_read_text)
        # 不应抛异常
        _maybe_print_plan_banner()
        captured = capsys.readouterr()
        assert captured.out == ""
        # 恢复避免影响其他测试（monkeypatch 会自动恢复）
        _ = original_read_text
    finally:
        plan_mode.exit()


# ── /plan 命令 ──────────────────────────────────────────────────────


def test_plan_command_enters_plan_mode():
    """/plan → 进入规划模式（planning），返回提示含计划文件路径。"""
    result = _process_plan_command()
    assert plan_mode.is_active is True
    assert plan_mode.status == plan_mode.STATUS_PLANNING
    assert "已进入规划模式" in result
    assert str(plan_mode.plan_path) in result


def test_plan_command_when_already_active():
    """已激活时再 /plan → 提示已在规划模式，不抛异常。"""
    plan_mode.enter()
    try:
        result = _process_plan_command()
        assert "已在规划模式中" in result
    finally:
        plan_mode.exit()


# ── /run 命令三分支 ─────────────────────────────────────────────────


def test_run_when_idle_hints():
    """/run：不在规划模式 → 提示，不抛。"""
    result = _process_run_command()
    assert "当前不在规划模式" in result


def test_run_when_unapproved_hints():
    """/run：计划未批准 → 提示先批准，状态不变。"""
    plan_mode.enter()
    try:
        write_plan(content="# 计划")
        result = _process_run_command()
        assert "尚未批准" in result
        assert plan_mode.is_active is True  # 未退出
    finally:
        plan_mode.exit()


def test_run_when_approved_exits():
    """/run：已批准 → 退出规划模式，返回执行提示。"""
    plan_mode.enter()
    try:
        write_plan(content="# 计划")
        plan_mode.approve()
        result = _process_run_command()
        assert "开始执行计划" in result
        assert plan_mode.is_active is False  # 已退出
    finally:
        plan_mode.exit()


# ── _process_user_input (plan 审批 slash 命令) ──────────────────────


def test_approve_in_plan_mode_sets_approved_and_returns_synthetic_message():
    """plan 模式内（计划已提交）/approve → 状态置 approved + 返回合成消息。"""
    plan_mode.enter()
    try:
        write_plan(content="# 计划")
        result = _process_user_input("/approve")
        assert result is not None
        assert "✓ 计划已批准" in result
        assert "exit_plan_mode" in result
        assert plan_mode.status == plan_mode.STATUS_APPROVED
    finally:
        plan_mode.exit()


def test_approve_outside_plan_mode_prints_and_returns_none(capsys):
    """plan 模式外 /approve → 打印友好提示，返回 None。"""
    result = _process_user_input("/approve")
    assert result is None
    captured = capsys.readouterr()
    assert "当前不在规划模式" in captured.out


def test_approve_before_submit_warns_and_returns_none(capsys):
    """plan 模式但计划未提交（planning）→ /approve 警告，返回 None。"""
    plan_mode.enter()
    try:
        result = _process_user_input("/approve")
        assert result is None
        captured = capsys.readouterr()
        assert "计划提交" in captured.out
    finally:
        plan_mode.exit()


def test_revise_with_feedback_in_plan_mode_returns_synthetic_message():
    """plan 模式内 /revise X → 状态打回 planning + 返回修改请求消息。"""
    plan_mode.enter()
    try:
        write_plan(content="# 计划")
        result = _process_user_input("/revise 阶段 2 改用 pandas")
        assert result is not None
        assert "📝 请按反馈修改计划" in result
        assert "阶段 2 改用 pandas" in result
        assert plan_mode.status == plan_mode.STATUS_PLANNING  # 状态打回
    finally:
        plan_mode.exit()


def test_revise_without_feedback_prints_usage_and_returns_none(capsys):
    """plan 模式内 /revise（无参数）→ 打印用法，返回 None。"""
    plan_mode.enter()
    try:
        result = _process_user_input("/revise")
        assert result is None
        captured = capsys.readouterr()
        assert "用法" in captured.out
    finally:
        plan_mode.exit()


def test_cancel_in_plan_mode_exits_and_returns_none(capsys):
    """plan 模式内 /cancel → 状态回 idle，返回 None。"""
    plan_mode.enter()
    write_plan(content="# 计划")
    assert plan_mode.is_active is True
    result = _process_user_input("/cancel")
    assert result is None
    assert plan_mode.is_active is False
    captured = capsys.readouterr()
    assert "已取消计划" in captured.out


def test_non_slash_input_passes_through_unchanged():
    """非审批命令（普通对话）→ 原样返回，由后续流程处理。"""
    result = _process_user_input("今天天气怎么样？")
    assert result == "今天天气怎么样？"


# ── plan_status_line（模型侧状态注入）────────────────────────────────


def test_plan_status_line_empty_when_inactive():
    """plan 未激活 → 返回空串（不注入）。"""
    assert plan_status_line() == ""


def test_plan_status_line_contains_state_when_active():
    """plan 激活 → 返回状态描述（状态 + 计划文件 + 规则）。"""
    plan_mode.enter()
    try:
        write_plan(content="# 计划")
        line = plan_status_line()
        assert "【框架状态】" in line
        assert "待审批" in line
        assert str(plan_mode.plan_path) in line
        assert "exit_plan_mode" in line
    finally:
        plan_mode.exit()

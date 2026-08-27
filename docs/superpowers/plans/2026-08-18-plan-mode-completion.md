# Plan Mode Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 完成 Plan Mode 三处缺口补全——双澄清提示词、专用 `write_plan` 工具、CLI 审批闭环（`/approve` `/revise` `/cancel` + REPL 计划 banner）。

**Architecture:** 在既有 `PlanMode` 状态机（`plan_mode.py`）+ `plan_guard`（`tool_runner.py`）+ REPL（`session_manager.py`）基础上：
- `plan_mode.py` 加 `write_plan` 工具（路径由框架绑定）+ 重写 `ENTER_GUIDANCE` / 微调 `EXIT_GUIDANCE` / 更新 `enter_plan_mode` 返回字符串
- `turn_context.py` 加"进入前自评需求清晰度"一条规则
- `session_manager.py` 加 `_maybe_print_plan_banner` + `_process_user_input` 辅助函数，REPL 主循环接入两者；测试只针对辅助函数（不直接测 `run_repl`，避免 mock `input()`）
- 新建 `tests/` 目录 + 两个测试文件

**Tech Stack:** Python 3.13+ / pytest（新增 dev 依赖）

## Global Constraints

- 不修改 `tool_runner.py` / `cli.py` / `conversation_loop.py` / `message_store.py` / `tools.py`（既有 plan_guard / 工具注册机制足够）
- 不引入额外运行时依赖（仅 dev 依赖加 pytest）
- `plan_mode` 是模块级单例；测试必须用 `autouse` fixture 重置 `_active` / `_plan_id` / `_plan_path` / `_plans_dir`，避免测试间状态污染
- 提示词保留中文（与既有项目一致）；路径 / 命令 / 标识符保留英文
- 所有新增工具走 `@tool(description=...)` 装饰器（自动注册到 `tool_runner._TOOL_REGISTRY`）
- 测试仅测新增/修改的辅助函数和工具，不 mock LLM 调用层

---

## File Structure

| 文件 | 改动 | 职责 |
|------|------|------|
| `pyproject.toml` | 修改 | 加 `[dependency-groups]` dev = `["pytest"]` |
| `tests/__init__.py` | 新增（空） | 标记 `tests/` 为 Python 包；避免与模块名冲突 |
| `tests/conftest.py` | 新增 | `reset_plan_mode` autouse fixture |
| `tests/test_plan_mode.py` | 新增 | write_plan 工具 + PlanMode 状态测试 |
| `tests/test_session_manager.py` | 新增 | `_maybe_print_plan_banner` + `_process_user_input` 测试 |
| `plan_mode.py` | 修改 | 加 `write_plan` 工具；重写 `ENTER_GUIDANCE`；微调 `EXIT_GUIDANCE`；更新 `enter_plan_mode` 返回字符串 |
| `turn_context.py` | 修改 | 在"复杂任务规划规则"前加规则 0 |
| `session_manager.py` | 修改 | 加 `_maybe_print_plan_banner` + `_process_user_input` + 接入 REPL 主循环；更新 `REPL_HELP` 文案 |

---

## Task 1: 搭建 pytest 测试基础设施

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

V2 当前无测试。pytest 是 Python 2026 生态标准（最少样板代码、最干净的 fixture 模型）。

- [ ] **Step 1: 在 `pyproject.toml` 加 pytest dev 依赖**

当前 `pyproject.toml`：
```toml
[project]
name = "minimal-agent-v2"
version = "0.1.0"
description = "Add your description here"
readme = "README.md"
requires-python = ">=3.13"
dependencies = [
    "openai==2.24.0",
]
```

修改后：
```toml
[project]
name = "minimal-agent-v2"
version = "0.1.0"
description = "Add your description here"
readme = "README.md"
requires-python = ">=3.13"
dependencies = [
    "openai==2.24.0",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
]
```

- [ ] **Step 2: 同步依赖并验证 pytest 可用**

Run:
```bash
cd /root/projects/minimal-agent-v2 && uv sync && .venv/bin/pytest --version
```

Expected: 安装成功，pytest 版本号（≥8.0）打印到 stdout。

If `uv` 不可用：`pip install pytest` 后用 `python -m pytest --version` 验证。

- [ ] **Step 3: 创建 `tests/__init__.py`（空文件）**

```bash
mkdir -p tests && touch tests/__init__.py
```

- [ ] **Step 4: 创建 `tests/conftest.py`（autouse fixture）**

写入文件 `tests/conftest.py`：

```python
"""共享 pytest fixture。

`reset_plan_mode` autouse fixture 在每个测试前后重置 `plan_mode` 模块级单例，
避免测试间状态污染（plan_mode._active / _plan_id / _plan_path / _plans_dir）。
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def reset_plan_mode(tmp_path):
    """每个测试前后重置 plan_mode 单例，plans_dir 指向临时目录。"""
    from plan_mode import plan_mode
    plan_mode._active = False
    plan_mode._plan_id = None
    plan_mode._plan_path = None
    plan_mode._plans_dir = tmp_path
    yield
    plan_mode._active = False
    plan_mode._plan_id = None
    plan_mode._plan_path = None
```

- [ ] **Step 5: 验证测试基础设施可用（sanity check）**

写入文件 `tests/test_smoke.py`（临时验证用，Task 2 末尾删除）：

```python
def test_smoke(tmp_path):
    assert tmp_path.exists()
```

Run:
```bash
cd /root/projects/minimal-agent-v2 && .venv/bin/pytest tests/test_smoke.py -v
```

Expected: PASS。

然后删除 `tests/test_smoke.py`：
```bash
rm tests/test_smoke.py
```

---

## Task 2: `write_plan` 工具（TDD：先写失败测试）

**Files:**
- Create: `tests/test_plan_mode.py`（仅 write_plan 部分）
- Modify: `plan_mode.py`（新增 `WRITE_PLAN_GUIDANCE` + `write_plan` 函数）

`write_plan(content)` 是新工具，仅在 plan_mode 激活时工作；路径由框架从 `plan_mode.plan_path` 绑定（模型只传 content）。空 content 拒绝；非 plan 模式返回错误。

- [ ] **Step 1: 写 4 个失败测试（覆盖正常路径 + 三类失败）**

写入文件 `tests/test_plan_mode.py`：

```python
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
```

- [ ] **Step 2: 运行测试，确认 4 个都失败**

Run:
```bash
cd /root/projects/minimal-agent-v2 && .venv/bin/pytest tests/test_plan_mode.py -v
```

Expected: 4 个测试全部 FAIL（`write_plan` 函数不存在），错误信息 `cannot import name 'write_plan'` 或 `function not defined`。

- [ ] **Step 3: 在 `plan_mode.py` 实现 `write_plan`**

打开 `plan_mode.py`，在 `EXIT_GUIDANCE` 之前（即 `ENTER_GUIDANCE` 之后、`@tool(description=EXIT_GUIDANCE)` 之前）插入：

```python
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
    return (
        f"已写入计划 ({len(content)} 字符, {plan_mode.plan_path})。"
        "等待用户审批：用户将输入 /approve (批准执行)、/revise <反馈> (修改) 或 /cancel (取消)。"
    )
```

- [ ] **Step 4: 运行测试，确认 4 个全部 PASS**

Run:
```bash
cd /root/projects/minimal-agent-v2 && .venv/bin/pytest tests/test_plan_mode.py -v
```

Expected: 4 个测试全部 PASS。

---

## Task 3: PlanMode 状态机测试（既有实现，加保护网）

**Files:**
- Modify: `tests/test_plan_mode.py`（追加 3 个测试）

`PlanMode` 类已实现（plan_mode.py:35-71）。本任务只为它加测试，防止后续重构破坏既有契约。

- [ ] **Step 1: 在 `tests/test_plan_mode.py` 追加 3 个测试**

在文件末尾追加：

```python


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
```

- [ ] **Step 2: 运行测试，确认 7 个全部 PASS**

Run:
```bash
cd /root/projects/minimal-agent-v2 && .venv/bin/pytest tests/test_plan_mode.py -v
```

Expected: 7 个测试全部 PASS（4 个 write_plan + 3 个 PlanMode）。

---

## Task 4: 提示词重写 + turn_context 规则

**Files:**
- Modify: `plan_mode.py`（`ENTER_GUIDANCE` 全文重写、`EXIT_GUIDANCE` 微调、`enter_plan_mode` 返回字符串更新）
- Modify: `turn_context.py`（规则 0 新增）

纯文案改动，无新逻辑、无新测试（既有 `write_plan` 测试已隐含契约；ENTER_GUIDANCE 是给 LLM 看的，不参与 Python 执行）。

- [ ] **Step 1: 重写 `ENTER_GUIDANCE`**

在 `plan_mode.py` 中找到 `ENTER_GUIDANCE` 常量（在 `enter_plan_mode` 函数定义之前），整段替换为：

```python
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
```

- [ ] **Step 2: 微调 `EXIT_GUIDANCE`**

找到 `EXIT_GUIDANCE` 常量，把第二行 `"调用前确保计划已用 write 写入计划文件"` 中的 `write` 替换为 `write_plan`：

修改前：
```python
EXIT_GUIDANCE = """退出规划模式，开始执行已批准的计划。
调用前确保计划已用 write 写入计划文件；退出后所有工具恢复可用。
执行规则：
1. 每完成一个阶段，先对照该阶段的验收条件验证结果；不满足则修正后重新验证
2. 全部阶段完成后，做整体验证：逐条核对所有验收条件，全部满足才向用户报告完成"""
```

修改后：
```python
EXIT_GUIDANCE = """退出规划模式，开始执行已批准的计划。
调用前确保计划已用 write_plan 写入计划文件；退出后所有工具恢复可用。
执行规则：
1. 每完成一个阶段，先对照该阶段的验收条件验证结果；不满足则修正后重新验证
2. 全部阶段完成后，做整体验证：逐条核对所有验收条件，全部满足才向用户报告完成"""
```

其余文字不动。

- [ ] **Step 3: 更新 `enter_plan_mode` 函数返回字符串**

找到 `enter_plan_mode()` 函数（在 `@tool(description=ENTER_GUIDANCE)` 装饰器下），其 `return (...)` 块整段替换为：

```python
    return (
        f"已进入规划模式。计划文件：{path}。"
        "工作流：调研 → write_plan 写入计划（覆盖式） → 等待用户输入 /approve / /revise / /cancel。"
        "收到\"已批准\"消息后，调 exit_plan_mode 开始执行。"
    )
```

- [ ] **Step 4: 在 `turn_context.py` 加规则 0**

打开 `turn_context.py`，找到 `"复杂任务规划规则："` 字符串块（紧跟其后的 `"1. 遇到多步骤、多文件或需要设计决策的任务..."`），在 `"1."` 行之前插入规则 0：

修改前：
```python
    base += """

复杂任务规划规则：
1. 遇到多步骤、多文件或需要设计决策的任务，先调用 enter_plan_mode 进入规划模式
...
```

修改后：
```python
    base += """

复杂任务规划规则：
0. 进入规划模式前先自评需求清晰度——若模糊（目标/范围/验收标准不明确），
   主动用对话/AskUserQuestion 向用户澄清关键问题，再 enter_plan_mode
1. 遇到多步骤、多文件或需要设计决策的任务，先调用 enter_plan_mode 进入规划模式
...
```

（其余规则 2-6 不动。）

- [ ] **Step 5: 验证：所有现有测试仍 PASS**

Run:
```bash
cd /root/projects/minimal-agent-v2 && .venv/bin/pytest tests/test_plan_mode.py -v
```

Expected: 7 个测试全部 PASS（文案改动不影响 Python 行为，但跑一遍确认无意外）。

---

## Task 5: REPL 计划 banner（TDD）

**Files:**
- Create: `tests/test_session_manager.py`（仅 banner 部分）
- Modify: `session_manager.py`（加 `_maybe_print_plan_banner` + 接入 REPL）

banner 在 plan 模式激活且计划文件存在时，自动打印当前计划内容供用户审查。IO 错误静默跳过，不破坏 REPL 主循环。

- [ ] **Step 1: 写 3 个失败测试**

在 `tests/test_session_manager.py` 写入：

```python
"""session_manager 测试：REPL banner + plan 审批 slash 命令辅助函数。

仅测试可独立调用的辅助函数，不直接测 run_repl（避免 mock input()）。
"""
from __future__ import annotations

import pytest

from plan_mode import plan_mode
from session_manager import _maybe_print_plan_banner


# ── _maybe_print_plan_banner ────────────────────────────────────────


def test_banner_prints_when_plan_active_and_file_exists(capsys, tmp_path):
    """plan 模式激活 + 文件存在 + 有内容 → 打印 banner 含内容。"""
    plan_mode.enter()
    try:
        plan_mode.plan_path.write_text("# 测试计划\n## 阶段 1\n- 目标 X\n- 验收 Y",
                                        encoding="utf-8")
        _maybe_print_plan_banner()
        captured = capsys.readouterr()
        assert "📋 当前计划" in captured.out
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
```

- [ ] **Step 2: 运行测试，确认 3 个都失败（`_maybe_print_plan_banner` 不存在）**

Run:
```bash
cd /root/projects/minimal-agent-v2 && .venv/bin/pytest tests/test_session_manager.py -v
```

Expected: 3 个测试 FAIL，错误信息 `cannot import name '_maybe_print_plan_banner'`。

- [ ] **Step 3: 更新 `REPL_HELP` 常量**

在 `session_manager.py` 中找到 `REPL_HELP` 常量，在 `/run` 行之后追加 3 行：

修改前：
```python
REPL_HELP = """/new <名字>   - 新建 session
/switch <名字|序号> - 切换 session（序号需先 /list 查看）
/list          - 列出所有 session
/delete <名字> - 删除 session
/plan          - 手动进入规划模式（Plan Mode：只读调研 + 只能写计划文件）
/run           - 退出规划模式，开始执行计划
/exit, /quit   - 退出"""
```

修改后：
```python
REPL_HELP = """/new <名字>   - 新建 session
/switch <名字|序号> - 切换 session（序号需先 /list 查看）
/list          - 列出所有 session
/delete <名字> - 删除 session
/plan          - 手动进入规划模式（Plan Mode：只读调研 + 只能写计划文件）
/run           - 退出规划模式，开始执行计划
/approve       - 批准当前计划（plan 模式专用）
/revise <反馈> - 要求模型按反馈修改计划（plan 模式专用）
/cancel        - 取消当前计划并退出 plan 模式
/exit, /quit   - 退出"""
```

- [ ] **Step 4: 在 `session_manager.py` 实现 `_maybe_print_plan_banner`**

在 `session_manager.py` 末尾（即 `run_repl` 函数之后、`_choose_session` 函数之前）插入新函数：

```python
def _maybe_print_plan_banner() -> None:
    """plan_mode 激活且计划文件存在时，打印当前计划内容供用户审查。

    静默处理 IO 错误（不影响 REPL 主循环）。
    调用时机：在 run_repl 主循环读 input() 之前。
    """
    from plan_mode import plan_mode
    if not plan_mode.is_active:
        return
    if plan_mode.plan_path is None or not plan_mode.plan_path.exists():
        return
    try:
        content = plan_mode.plan_path.read_text(encoding="utf-8")
    except OSError:
        return
    print(f"\n📋 当前计划（{plan_mode.plan_path}）:")
    print("─" * 60)
    print(content if content else "<空>")
    print("─" * 60)
```

- [ ] **Step 5: 运行测试，确认 3 个全部 PASS**

Run:
```bash
cd /root/projects/minimal-agent-v2 && .venv/bin/pytest tests/test_session_manager.py -v
```

Expected: 3 个 banner 测试 PASS。

- [ ] **Step 6: 接入 REPL 主循环**

找到 `run_repl` 函数，在 `while True:` 循环里 `try:` 块内 `input(...)` 调用之前插入一行。

修改前：
```python
    while True:
        try:
            user_input = input(REPL_PROMPT.format(name=session.name)).strip()
        except (EOFError, KeyboardInterrupt):
```

修改后：
```python
    while True:
        try:
            _maybe_print_plan_banner()                 # ← 新增：plan 模式时打印当前计划
            user_input = input(REPL_PROMPT.format(name=session.name)).strip()
        except (EOFError, KeyboardInterrupt):
```

- [ ] **Step 7: 验证测试仍 PASS**

Run:
```bash
cd /root/projects/minimal-agent-v2 && .venv/bin/pytest tests/ -v
```

Expected: 所有测试 PASS（7 个 plan_mode + 3 个 session_manager = 10 个）。

---

## Task 6: Plan 审批 slash 命令辅助函数（TDD）

**Files:**
- Modify: `tests/test_session_manager.py`（追加 6 个测试）
- Modify: `session_manager.py`（加 `_process_user_input` + 接入 REPL）

3 个 slash 命令（`/approve` / `/revise` / `/cancel`）通过 `_process_user_input` 辅助函数集中处理，便于测试。函数签名：`(user_input) -> Optional[str]`，返回 None = REPL 跳过该输入；返回字符串 = 替换为该字符串注入对话。

- [ ] **Step 1: 在 `tests/test_session_manager.py` 追加 6 个失败测试**

在文件顶部 `from session_manager import _maybe_print_plan_banner` 那一行附近，**同位置**追加一行 `from session_manager import _process_user_input`，然后在文件末尾追加测试块：

```python


# ── _process_user_input (plan 审批 slash 命令) ──────────────────────


def test_approve_in_plan_mode_returns_synthetic_message():
    """plan 模式内 /approve → 返回"✓ 计划已批准..."合成消息。"""
    plan_mode.enter()
    try:
        result = _process_user_input("/approve")
        assert result is not None
        assert "✓ 计划已批准" in result
        assert "exit_plan_mode" in result
    finally:
        plan_mode.exit()


def test_approve_outside_plan_mode_prints_and_returns_none(capsys):
    """plan 模式外 /approve → 打印友好提示，返回 None。"""
    result = _process_user_input("/approve")
    assert result is None
    captured = capsys.readouterr()
    assert "当前不在规划模式" in captured.out


def test_revise_with_feedback_in_plan_mode_returns_synthetic_message():
    """plan 模式内 /revise X → 返回"📝 请按反馈修改计划：X"。"""
    plan_mode.enter()
    try:
        result = _process_user_input("/revise 阶段 2 改用 pandas")
        assert result is not None
        assert "📝 请按反馈修改计划" in result
        assert "阶段 2 改用 pandas" in result
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
    """plan 模式内 /cancel → 调 plan_mode.exit()，返回 None。"""
    plan_mode.enter()
    assert plan_mode.is_active is True
    result = _process_user_input("/cancel")
    assert result is None
    assert plan_mode.is_active is False
    captured = capsys.readouterr()
    assert "已退出规划模式" in captured.out


def test_non_slash_input_passes_through_unchanged():
    """非审批命令（普通对话）→ 原样返回，由后续流程处理。"""
    result = _process_user_input("今天天气怎么样？")
    assert result == "今天天气怎么样？"
```

- [ ] **Step 2: 运行测试，确认 6 个都失败**

Run:
```bash
cd /root/projects/minimal-agent-v2 && .venv/bin/pytest tests/test_session_manager.py -v
```

Expected: 6 个测试 FAIL（`_process_user_input` 不存在）。

- [ ] **Step 3: 在 `session_manager.py` 实现 `_process_user_input`**

在 `_maybe_print_plan_banner` 函数后（即 `session_manager.py` 末尾，`_choose_session` 之前）追加：

```python
def _process_user_input(user_input: str) -> Optional[str]:
    """处理 plan 审批 slash 命令（/approve / /revise / /cancel）。

    返回值：
      - None：REPL 应跳过当前输入（continue）
      - 字符串：替换 user_input 为该值注入对话（可能是合成消息）

    非审批命令（含 /plan / /run / 普通对话）：原样返回 user_input。
    """
    # /approve
    if user_input.lower() == "/approve":
        from plan_mode import plan_mode
        if not plan_mode.is_active:
            print("ℹ️  当前不在规划模式。")
            return None
        return "✓ 计划已批准，请调 exit_plan_mode 开始执行。"

    # /revise
    if user_input.lower().startswith("/revise"):
        from plan_mode import plan_mode
        feedback = user_input[len("/revise"):].strip()
        if not plan_mode.is_active:
            print("ℹ️  当前不在规划模式（输入 /plan 进入）。")
            return None
        if not feedback:
            print("用法：/revise <反馈内容>")
            return None
        return f"📝 请按反馈修改计划：{feedback}"

    # /cancel
    if user_input.lower() == "/cancel":
        from plan_mode import plan_mode
        if plan_mode.is_active:
            plan_mode.exit()                              # REPL 直接清状态
            print("✗ 已退出规划模式（计划已取消）。")
        else:
            print("ℹ️  当前不在规划模式。")
        return None

    # 非审批命令，原样返回
    return user_input
```

并在文件顶部 `from typing import Optional` 已有，无需新增 import。

- [ ] **Step 4: 运行测试，确认 9 个 session_manager 测试全部 PASS**

Run:
```bash
cd /root/projects/minimal-agent-v2 && .venv/bin/pytest tests/test_session_manager.py -v
```

Expected: 9 个测试 PASS（3 banner + 6 slash 命令）。

- [ ] **Step 5: 接入 REPL 主循环**

找到 `run_repl` 函数，在 `/run` 命令处理器（`if user_input.lower() == "/run":` 块，含其 `continue` 结束）之后、`if user_input.startswith("/"):` 通用命令处理器之前插入新代码。

修改前（`/run` 块结束，紧接通用命令处理）：
```python
        if user_input.lower() == "/run":
            from plan_mode import plan_mode
            if plan_mode.is_active:
                plan_mode.exit()
                print("▶️ 已退出规划模式，所有工具恢复可用。开始执行计划。")
            else:
                print("ℹ️ 当前不在规划模式（输入 /plan 进入）。")
            continue

        # 处理命令
        if user_input.startswith("/"):
            new_session = _handle_command(user_input, session, manager, loop)
            if new_session is not None:
                session = new_session
            continue
```

修改后：
```python
        if user_input.lower() == "/run":
            from plan_mode import plan_mode
            if plan_mode.is_active:
                plan_mode.exit()
                print("▶️ 已退出规划模式，所有工具恢复可用。开始执行计划。")
            else:
                print("ℹ️ 当前不在规划模式（输入 /plan 进入）。")
            continue

        # Plan Mode 审批命令（/approve / /revise / /cancel）— 新增 ──
        processed = _process_user_input(user_input)
        if processed is None:
            continue
        user_input = processed

        # 处理命令
        if user_input.startswith("/"):
            new_session = _handle_command(user_input, session, manager, loop)
            if new_session is not None:
                session = new_session
            continue
```

注意：`_process_user_input` 仅处理 3 个新命令；原有 `/plan` / `/run` / `/exit` / `/quit` / 其他 `/xxx` 命令继续走原路径。

- [ ] **Step 6: 全量回归测试**

Run:
```bash
cd /root/projects/minimal-agent-v2 && .venv/bin/pytest tests/ -v
```

Expected: 16 个测试全部 PASS（7 plan_mode + 9 session_manager）。

---

## Task 7: 集成验证（手动 REPL 烟雾测试）

**Files:** 无（验证步骤）

代码改动完成，跑一次真实 CLI 流程确认端到端工作。

- [ ] **Step 1: REPL 启动 + 帮助文本确认**

Run:
```bash
cd /root/projects/minimal-agent-v2 && .venv/bin/python cli.py -i
```

在 REPL 中输入 `/help` 或类似命令（查看 REPL_HELP 是否包含 `/approve` / `/revise` / `/cancel`）。

Expected: 帮助文本显示新增的 3 个 slash 命令。

如果 REPL 没有 `/help` 命令，直接看代码：`grep -A 3 "REPL_HELP" session_manager.py` 应能看到完整文案。

- [ ] **Step 2: 端到端审批闭环**

在 REPL 中输入以下序列（手动模拟一次完整 plan 模式流程）：

```
💬 /plan
→ 期望：打印 "📋 已进入规划模式，计划文件：..."
💬 测试任务
→ 期望：模型调用 enter_plan_mode → (因为是新 REPL 启动，已在 plan 模式，会跳过)
       → 调 read / ls 调研 → 调 write_plan 写计划 → 打印"等待用户审批"
💬 /approve
→ 期望：REPL 打印 banner（含刚才写入的计划内容），合成"✓ 计划已批准..."消息注入对话，
       模型收到后调 exit_plan_mode，开始执行
💬 /exit
→ 期望：REPL 退出
```

如果模型在 `/approve` 后未自动调 `exit_plan_mode`：手动输入 `/run` 兜底（既有能力）。

- [ ] **Step 3: /revise 流程**

重新启动 REPL，重复 enter_plan_mode + write_plan，但这次输入：
```
💬 /revise 把阶段 2 改用 pandas 实现
→ 期望：合成"📝 请按反馈修改计划：把阶段 2 改用 pandas 实现"消息，
       模型收到后调 write_plan 写入新计划
```

确认计划文件被更新（可手动 `cat ~/.minimal-agent-v2/plans/plan-*.md` 查看最后修改时间）。

- [ ] **Step 4: /cancel 流程**

再次启动 REPL，enter_plan_mode + write_plan，然后：
```
💬 /cancel
→ 期望：REPL 直接调 plan_mode.exit()，打印"✗ 已退出规划模式（计划已取消）"，
       后续对话中模型不再受 plan 模式约束
```

- [ ] **Step 5: plan 模式外使用审批命令**

非 plan 模式下输入：
```
💬 /approve
→ 期望：打印"ℹ️  当前不在规划模式。"，不注入消息
💬 /revise 测试
→ 期望：打印"ℹ️  当前不在规划模式（输入 /plan 进入）。"
💬 /cancel
→ 期望：打印"ℹ️  当前不在规划模式。"
```

---

## Self-Review Checklist（执行前对照 spec 自查）

实现完成后对照 `docs/superpowers/specs/2026-08-17-plan-mode-completion-design.md` 验证：

- [ ] spec §2：`write_plan` 工具实现（含未在 plan 模式报错、空 content 拒绝、覆盖语义、返回字符数）—— Task 2 测试覆盖
- [ ] spec §3：ENTER_GUIDANCE 全文重写 + EXIT_GUIDANCE 微调 + enter_plan_mode 返回字符串更新 —— Task 4
- [ ] spec §4：turn_context.py 规则 0 新增 —— Task 4
- [ ] spec §5.1：`_maybe_print_plan_banner` 实现（含 OSError 静默） —— Task 5 测试覆盖
- [ ] spec §5.2：3 个 slash 命令通过 `_process_user_input` 集中处理 —— Task 6 测试覆盖
- [ ] spec §5.2：banner + slash 命令接入 REPL 主循环 —— Task 5/6 接入步骤
- [ ] spec §6：用户未提交改动（line 111 / line 126 "请求批准" 语义）被新 ENTER_GUIDANCE 覆盖 —— Task 4
- [ ] spec 错误处理表：所有列出的错误场景都有对应处理路径（write_plan / slash 命令 / banner 各自的边界）
- [ ] spec 不在本期范围：方案选项 / 动态重规划 / read_plan / update_plan_section 都没新增 —— 任务清单无相关条目
- [ ] Global Constraints：tool_runner.py / cli.py / conversation_loop.py 未修改 —— 任务清单未涉及
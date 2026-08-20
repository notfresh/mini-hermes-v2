# Plan Mode Completion — 双澄清 + 专用写计划 + CLI 审批闭环

> Spec for: minimal-agent-v2
> Status: approved (pending user review)
> Date: 2026-08-17
> 范围：在 `plan-mode-v2` 既有 `PlanMode` 状态机 + `enter_plan_mode` / `exit_plan_mode` + `plan_guard` 基础上，补全三处缺口：
>   1. 提示词未让模型主动向用户澄清需求
>   2. 写计划依赖通用 `write` 工具（模型必须记对路径）
>   3. exit_plan_mode 之前没有真正的用户审批信号（用户未提交改动已写入"请求批准"提示词，但下游无对应机制）

## 目标

把 Plan Mode 从"提示词约束的半成品"升级为"框架闭环的可用功能"：

1. **双澄清**：进入规划模式前 + 规划模式中遇到关键设计决策时，模型主动向用户提问
2. **专用 `write_plan` 工具**：路径由框架绑定，模型只传内容，消除拼错路径风险
3. **CLI 审批闭环**：3 个 slash 命令 `/approve` `/revise` `/cancel` + REPL 自动展示当前计划，用户实际能给出批准信号；模型收到"已批准"消息后才调 `exit_plan_mode`

镜像 Kimi CLI 的 Plan Mode 闭环思路，但简化为单方案（不支持 1-3 方案选项，方案 C 留待 V3）。

## 设计范围

- **修改**：`plan_mode.py`（新工具 + 提示词重写）、`session_manager.py`（3 个 slash 命令 + banner 辅助）、`turn_context.py`（规则加一条）
- **新增**：`tests/test_plan_mode.py`、`tests/test_session_manager.py`
- **不修改**：`tool_runner.py`（`plan_guard` 现状够用）、`cli.py`（import 即注册，无需改动）、`conversation_loop.py`、`message_store.py`、`tools.py`

## 核心设计

### 1. 工作流（双澄清 + 审批闭环）

```
用户: "做CSV解析工具"
   ↓
模型: 自评需求是否清晰
   ├─ 不清晰 → 主动向用户问 1-3 个澄清问题（用对话/AskUserQuestion）
   └─ 清晰 ↓
模型: enter_plan_mode → 拿到 plan_path
模型: 只读调研（read / ls / grep）
   ↓
调研中遇到关键设计决策不确定？→ 再问用户
   ↓
模型: write_plan(content=完整计划) → 告知用户"等待审批"
   ↓
[REPL 自动打印当前计划 banner]
   ↓
用户: /approve | /revise <反馈> | /cancel
   ├─ /revise → 模型重写 write_plan → 循环
   └─ /approve 或 /cancel → 模型调 exit_plan_mode → 执行或中止
```

### 2. `write_plan` 工具（plan_mode.py 新增）

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
      - 未在 plan 模式：返回错误（自保护）
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

**关键点**：
- 路径由框架从 `plan_mode.plan_path` 绑定，模型只传 `content`，消除拼写错误
- 不修改 `plan_guard`：write_plan 是新工具，不在拦截范围；通用 `write` 仍按现有规则运行（plan 模式下写非计划文件 → 拒绝）
- `write_plan` 在非 plan 模式下自保护：返回错误而不是抛异常，与工具返回字符串的契约一致

### 3. 提示词更新（plan_mode.py）

#### `ENTER_GUIDANCE` 全文重写

```
进入规划模式。适用于：多步骤 / 多文件 / 需要设计决策的复杂任务——先拆解计划、获得认可，再开始执行。
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
5. 收到"✓ 计划已批准"消息后，调 exit_plan_mode 开始执行
```

#### `EXIT_GUIDANCE` 微调

```
退出规划模式，开始执行已批准的计划。
调用前确保计划已用 write_plan 写入计划文件；退出后所有工具恢复可用。
执行规则：
1. 每完成一个阶段，先对照该阶段的验收条件验证结果；不满足则修正后重新验证
2. 全部阶段完成后，做整体验证：逐条核对所有验收条件，全部满足才向用户报告完成
```

#### `enter_plan_mode` 函数返回值同步更新

当前函数返回字符串（含未提交改动的"请求批准"语义）需改写为：

```
已进入规划模式。计划文件：{path}。
工作流：调研 → write_plan 写入计划（覆盖式） → 等待用户输入 /approve / /revise / /cancel。
收到"已批准"消息后，调 exit_plan_mode 开始执行。
```

### 4. turn_context.py 规则更新

在"复杂任务规划规则"第 1 条之前新增一条：

```
0. 进入规划模式前先自评需求清晰度——若模糊（目标/范围/验收标准不明确），
   主动用对话/AskUserQuestion 向用户澄清关键问题，再 enter_plan_mode
```

### 5. CLI 审批命令 + REPL 计划 banner（session_manager.py）

#### 5.1 `_maybe_print_plan_banner`（辅助函数）

```python
def _maybe_print_plan_banner():
    """plan_mode 激活且计划文件存在时，打印当前计划内容供用户审查。

    静默处理 IO 错误（不影响 REPL 主循环）。
    """
    from plan_mode import plan_mode
    if not plan_mode.is_active:
        return
    if plan_mode.plan_path is None or not plan_mode.plan_path.exists():
        return
    try:
        content = plan_mode.plan_path.read_text(encoding="utf-8")
    except OSError:
        return                                       # 静默失败,REPL 继续
    print(f"\n📋 当前计划（{plan_mode.plan_path}）:")
    print("─" * 60)
    print(content if content else "<空>")
    print("─" * 60)
```

调用时机：在 `run_repl` 主循环读 `input("💬 你的消息: ")` 之前。

#### 5.2 3 个 slash 命令（在现有 `/plan` `/run` 同位）

```python
# 在用户输入分支处理前先打印 banner
_maybe_print_plan_banner()

user_input = input("💬 你的消息: ").strip()

# ── Plan Mode 命令: 用户手动进入/退出规划模式（已有）──
if user_input.lower() == "/plan": ...
if user_input.lower() == "/run": ...

# ── 新增: 计划审批命令 ──
if user_input.lower().startswith("/revise"):
    from plan_mode import plan_mode
    feedback = user_input[len("/revise"):].strip()
    if not plan_mode.is_active:
        print("ℹ️  当前不在规划模式（输入 /plan 进入）。")
        continue
    if not feedback:
        print("用法：/revise <反馈内容>")
        continue
    # 合成用户消息，让模型据此重写计划
    user_input = f"📝 请按反馈修改计划：{feedback}"
    # 注意:不 continue,让正常流程把 user_input 注入对话

if user_input.lower() == "/approve":
    from plan_mode import plan_mode
    if not plan_mode.is_active:
        print("ℹ️  当前不在规划模式。")
        continue
    user_input = "✓ 计划已批准，请调 exit_plan_mode 开始执行。"

if user_input.lower() == "/cancel":
    from plan_mode import plan_mode
    if plan_mode.is_active:
        plan_mode.exit()         # REPL 直接清状态（避免模型忘记调）
        print("✗ 已退出规划模式（计划已取消）。")
        continue
    print("ℹ️  当前不在规划模式。")
    continue
```

**关键点**：
- `/approve` 和 `/revise`：合成用户消息走对话通道——模型是状态机权威，统一从 `exit_plan_mode` 出口
- `/cancel`：REPL 直接调 `plan_mode.exit()`（模型可能不调，统一从 REPL 兜底，保证状态一致）
- banner 调用时机：仅在 plan 模式激活 + 计划文件存在时打印，避免污染普通对话

### 6. 现有未提交改动整合

用户当前工作区已有两处对 `plan_mode.py` 的未提交修改（line 111 + line 126）：
- 移除了 "调 exit_plan_mode 退出规划模式"
- 添加 "请求用户批准才能开始执行"

本次设计会把 `ENTER_GUIDANCE` 整段重写（覆盖这两处），新版本保留并扩展"请求用户批准"语义，且补上对应的下游审批命令。两处未提交改动自然被吸收，无冲突。

## 数据模型

无新增类。复用现有 `PlanMode`（`plan_mode.py`）和模块级单例 `plan_mode`。`write_plan` 是新工具，状态完全由 `plan_mode` 持有。

## 错误处理

| 场景 | 行为 |
|------|------|
| `write_plan` 在非 plan 模式被调用 | 返回 "错误：未在规划模式"，工具不抛异常 |
| `write_plan` 收到空 content | 返回 "错误：计划内容不能为空" |
| `write_plan` 写入 IO 失败 | 抛异常（继承 `pathlib.Path.write_text` 行为）；上层 ToolRunner.execute 捕获为 error result |
| `/approve` 在非 plan 模式 | 友好提示 "当前不在规划模式" |
| `/revise` 无反馈内容 | 提示 "用法：/revise <反馈内容>" |
| `/cancel` 在非 plan 模式 | 友好提示 "当前不在规划模式" |
| REPL 读计划文件失败（IO 错误） | `try/except OSError` 包装 banner 函数，失败时静默跳过（不破坏主循环） |
| banner 在 plan 模式但 plan_path 为 None | 不打印（防御性：理论上不应发生） |

## 测试策略

### 新增 `tests/test_plan_mode.py`

1. `test_write_plan_requires_active`：plan_mode 未激活时调用 → 返回"未在规划模式"错误
2. `test_write_plan_rejects_empty`：plan 模式激活但 content 为空 → 返回"内容不能为空"错误
3. `test_write_plan_writes_content`：plan 模式激活 + 正常 content → 文件被覆盖写入，返回字符数
4. `test_write_plan_overwrite_semantics`：先写 A 再写 B → 文件内容 = B（A 不残留）
5. `test_plan_mode_enter_exit`：标准 enter/exit 流程，is_active 状态正确切换
6. `test_plan_mode_double_enter`：连续 enter 抛 RuntimeError
7. `test_plan_mode_exit_when_inactive`：未激活时 exit 不抛异常（幂等）

### 新增 `tests/test_session_manager.py`

1. `test_approve_synthesizes_message`：mock input → /approve 注入"✓ 计划已批准..."消息
2. `test_approve_outside_plan_mode`：plan 模式外 /approve 提示友好信息
3. `test_revise_with_feedback`：/revise X → 合成"📝 请按反馈修改计划：X"
4. `test_revise_without_feedback`：/revise（无参数）→ 提示用法
5. `test_revise_outside_plan_mode`：plan 模式外 /revise 提示友好信息
6. `test_cancel_clears_state`：plan 模式内 /cancel → plan_mode.is_active=False
7. `test_cancel_outside_plan_mode`：plan 模式外 /cancel 提示友好信息
8. `test_banner_prints_when_plan_active_and_exists`：plan 模式 + 文件存在 → 打印内容
9. `test_banner_skipped_when_plan_inactive`：plan 模式关闭 → 不打印
10. `test_banner_skipped_when_file_missing`：plan 模式激活但 plan_path 不存在 → 不打印
11. `test_banner_handles_io_error`：读文件失败 → 不抛异常，REPL 继续

## 兼容性

- **向后兼容**：现有 `enter_plan_mode` / `exit_plan_mode` / `plan_guard` 行为不变；新增 `write_plan` 是新工具，不影响已有调用
- **CLI 兼容**：无需新 flag；`/plan` `/run` 行为不变；新增 `/approve` `/revise` `/cancel` 仅在 plan 模式生效
- **数据兼容**：计划文件路径格式不变（`~/.minimal-agent-v2/plans/plan-YYYYMMDD-HHMMSS.md`），旧计划文件可被新代码读取
- **状态兼容**：`plan_mode` 模块级单例状态不变；既有 REPL 会话中激活的 plan_mode 在 reload 后会丢失（与现状一致）

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| LLM 跳过双澄清直接 enter_plan_mode | 提示词强提示（"模糊则先问用户"），但不强约束（不阻塞流程）——这是软澄清，与 Kimi 设计一致 |
| LLM 在写计划时仍用通用 `write` 工具 | `write_plan` 提示词明确"不要用通用 write"；且通用 `write` 在 plan 模式下仍受 `plan_guard` 限制 |
| `/approve` 合成消息被模型忽略（未调 exit_plan_mode） | 提示词强提示 + 提示词明文"收到批准消息后调 exit_plan_mode"；如果模型仍不调，用户可手动输入 `/run` 退出（已有能力） |
| `/cancel` 后状态不一致（REPL 已清但模型仍以为在 plan 模式） | `/cancel` REPL 直接调 `plan_mode.exit()` 同步清状态；下次模型调 `write_plan` / `exit_plan_mode` 会收到错误提示自纠正 |
| REPL banner 读大计划文件慢 | 计划文件通常 <10KB（几屏文本），IO 毫秒级；可接受 |
| 用户输入 `/approve` 时 banner 已存在计划文件不存在 | banner 防御性检查（`plan_path.exists()`），不打印 |

## 不在本期范围

- **方案选项**（Kimi ExitPlanMode 支持 1-3 个方案）：本期单方案（V3 候选）
- **动态重规划**（执行中 `/plan` 进入规划模式）：本期不做（设计 doc § 2 方案 C 的内容）
- **跨 session 的 plan 持久化**：本期沿用文件级隔离（每 plan 一个 .md 文件）
- **计划文件版本控制**（diff 旧/新版本）：本期不实现
- **`update_plan_section` 增量编辑**：本期不提供，模型必须 write_plan 写完整版
- **`read_plan` 专用工具**：本期不提供，模型用通用 `read` 即可
- **bash 工具可绕守卫**（已知 V2 简化边界）：本次不动；plan_mode 是 write 守卫，bash 行为与现状一致
# Plan Mode V3：审批硬闭环（真正做完 /approve /revise /cancel）

> 日期：2026-08-20 ｜ 分支：plan-mode-completion
> 前作：docs/design-20260812-plan-mode.md（三版递进）、docs/superpowers/specs/2026-08-17-plan-mode-completion-design.md（双澄清 + write_plan + 审批命令雏形）
> 本设计在「雏形已实现但未闭环」的基础上，把审批从**提示词软约束**升级为**框架硬状态**。

---

## 一、现状盘点：为什么说"没做好"

8-17 spec 的三处缺口（双澄清 / write_plan / CLI 审批命令）**代码上都已落地**，测试 16 个全绿。
但"审批"实际是**假闭环**：

| 环节 | 现状 | 问题 |
|------|------|------|
| `/approve` | 往对话注入一条消息「✓ 计划已批准，请调 exit_plan_mode」 | **状态机里没有 approved 字段**——这条消息只是提示词，模型可无视 |
| `exit_plan_mode` 工具 | 任何时刻调用都放行 | **模型不等审批就能退出规划模式开始执行**，审批形同虚设 |
| `plan_guard` | 只拦 write 非计划文件 | 拦不住"提前退出"这条更关键的路 |
| 模型感知状态 | 从工具返回值推断 | 状态对模型不可见，模型可能"忘记"自己在规划模式 |
| `/run` | 无脑退出 | 不检查是否已批准，和 /cancel 语义混淆 |

一句话：**审批是"请模型自觉"，不是"框架强制"。** 而 Plan Mode 的教学核心恰恰是
「谁在强制」——V3 就是把"等待审批"从模型上下文挪进框架内存。

## 二、设计：四状态审批状态机

### 2.1 状态迁移

```
        /plan 或 enter_plan_mode           write_plan(非空)
 idle ───────────────────────▶ planning ─────────────────▶ awaiting_approval
   ▲                              │  ▲                          │
   │                              │  │                          │ /approve
   │                              │  └──── /revise <反馈> ──────┘
   │                              │                              ▼
   └──────── /cancel ◀────────────┴────────────────────────── approved
   └──────── exit_plan_mode（仅 approved 可调）──────────────────▶ idle
```

| 状态 | 含义 | 谁进入 | 谁离开 |
|------|------|--------|--------|
| `idle` | 无规划 | 初始 / cancel / exit | enter |
| `planning` | 调研中，计划未提交 | enter | write_plan → awaiting；cancel → idle |
| `awaiting_approval` | 计划已提交，**等待用户审批** | write_plan | approve → approved；revise → planning；cancel → idle |
| `approved` | 用户已批准 | approve | exit_plan_mode → idle；cancel → idle |

关键决策：**`/revise` 把状态打回 `planning`**（不是 awaiting 的变体）——模型必须
重写计划、重新提交（write_plan 再次置为 awaiting），才能再次被审批。保证
「每次审批的对象都是最新版本」。

### 2.2 守卫升级：exit_plan_mode 也要过闸

`plan_guard` 在现有 write 拦截基础上，**新增拦截 exit_plan_mode**：

```
规划模式激活时：
  write 且目标 ≠ 计划文件       → DENIED（现状不变）
  exit_plan_mode 且 status ≠ approved → DENIED（新增）
     拒绝文案：「计划尚未获用户批准（当前状态：规划中/待审批）。
                必须等用户输入 /approve 批准后才能退出规划模式。」
```

这就是"硬"的本质：**模型想提前跑，框架不让**。模型收到 DENIED 后会读计划、
等用户审批——错误回填给模型（不崩溃、可见、可自我纠正），与现有守卫同一哲学。

### 2.3 REPL 命令语义（人类是权威，框架只管模型）

| 命令 | 行为 |
|------|------|
| `/plan` | enter → planning；打印提示（现状不变） |
| `/approve` | 状态机置 approved；打印「✓ 计划已批准」；注入批准消息给模型 |
| `/revise <反馈>` | 状态机打回 planning；注入反馈消息给模型（模型据此重写） |
| `/cancel` | 清空状态回 idle；打印「✗ 已取消」；计划文件保留（审计） |
| `/run` | 三态分支：approved → 退出执行；awaiting/planning → 提示"先 /approve 或 /revise 或 /cancel"；idle → 提示不在规划模式 |

设计决策：**`/run` 不强制要求批准**——人类是最高权威，可以随时强制退出；
被硬约束的只有模型（exit_plan_mode 工具）。这正是「谁在强制」的教学点：
**框架强制模型，不强制人类**。

### 2.4 模型侧状态注入（状态对模型可见）

REPL 每次把用户消息送进 loop 前，若 plan 激活，自动拼上状态前缀：

```
【框架状态】当前处于规划模式（待审批）。计划文件：~/.minimal-agent-v2/plans/plan-xxx.md。
规则：只允许只读调研与写入计划文件；调用 exit_plan_mode 前必须先获得用户 /approve 批准。

用户消息：...
```

配套：`turn_context.py` 新增 `plan_status_line()` 纯函数生成这段文本（可单测）。
注入位置在 REPL 层（`run_repl` 主循环），因为 REPL 走 `initial_messages` 恢复路径、
系统提示词不重建——**注入点必须选在每次都会执行的地方**。

### 2.5 会话切换防御

`plan_mode` 是模块级单例，跨 session 会串状态。`/new`、`/switch` 时若 plan 激活：
打印提示并自动 cancel（防止把 A 会话的规划状态带进 B 会话）。

---

## 三、改动面

| 文件 | 改动 |
|------|------|
| `plan_mode.py` | `PlanMode` 加 `status`（idle/planning/awaiting/approved）+ `approve()`/`revise()`/`cancel()` 方法；`plan_guard` 拦截 `exit_plan_mode`；`write_plan` 置 awaiting；工具提示词微调 |
| `turn_context.py` | 新增 `plan_status_line()`（读 plan_mode 状态生成注入文本，plan 未激活返回空串） |
| `session_manager.py` | `/approve` `/revise` `/cancel` `/run` 升级为状态机驱动；用户消息拼状态前缀；`/new` `/switch` 防御性 cancel；banner 显示状态标签；REPL_HELP 文案更新 |
| `tests/conftest.py` | reset fixture 增加 `_status` 字段 |
| `tests/test_plan_mode.py` | 新增状态机迁移测试 + 守卫 exit 拦截测试 |
| `tests/test_session_manager.py` | 新增 /run 三分支、/approve 状态迁移、状态前缀注入测试 |

**不改**：`tool_runner.py`（守卫检查点已通用）、`cli.py`、`conversation_loop.py`、
`message_store.py`、`tools.py`。

## 四、验证方式（明早验收路径）

1. **单元测试**：`uv run pytest tests/ -v` —— 覆盖状态机全迁移、守卫双拦截、
   REPL 命令三分支、状态注入
2. **人工场景**（真实 LLM）：
   - `/plan` → 描述任务 → 模型调研 + write_plan → banner 显示「待审批」
   - 直接要求模型"现在开始执行"→ 模型调 exit_plan_mode → **DENIED**（演示硬约束）
   - `/approve` → 模型调 exit_plan_mode → 放行 → 按计划执行
   - `/revise` 一轮 → 模型重写 → 再 /approve → 执行

## 五、不在本期范围（YAGNI）

- 多方案选项（Kimi ExitPlanMode 的 1-3 方案选择）——留给下一个版本
- 动态重规划（执行中再次 /plan）
- 跨 session 的 plan 持久化（用 /new /switch 清理兜底）
- bash 工具可绕守卫（已知简化边界，V2 就声明过）
- 计划文件版本控制（revise 的历史 diff）

## 六、教学点（这个设计讲什么）

- **软 vs 硬**：V1 提示词自觉 → V2 守卫拦 write → V3 守卫拦"提前退出"——强制力度逐级加深，落点始终在工具执行前
- **状态在哪**：审批状态在框架内存（PlanMode.status），不在模型上下文——模型"无法忘记"未批准
- **谁在强制**：框架强制模型（exit 需批准），不强制人类（/run 随时可退）——人类是权威

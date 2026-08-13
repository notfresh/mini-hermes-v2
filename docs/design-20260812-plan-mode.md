# MinimalAgent V2 — Plan Mode 设计方案

日期：2026-08-12
状态：讨论稿（未实现）
范围：在 V2 五模块骨架上实现"任务规划与执行"（Plan Mode / Plannable）

---

## 0. 调研结论

### 0.1 Kimi Code 是什么技术栈？

**TypeScript monorepo（Node.js 生态）**：
- 根 `package.json`：`"type": "module"`，pnpm workspace，Node.js >= 24.15.0
- 结构：`packages/agent-core`（引擎，含 plan）、`apps/kimi-code`（CLI/TUI）、`packages/kosong`（LLM 抽象层）等
- plan 逻辑全在 `packages/agent-core/src/agent/plan/` + `tools/builtin/planning/` + `permission/policies/`

### 0.2 Kimi Code Plan Mode 核心逻辑（四件套）

| 组件 | 文件 | 职责 |
|------|------|------|
| 状态机 | `agent/plan/index.ts` | `PlanMode` 类：`_isActive` / `_planId` / `_planFilePath`，enter()/exit()/cancel()。v2 引擎（planOps.ts）演化为持久化、可重放的 `{active, id}` 状态 |
| 入口工具 | `tools/builtin/planning/enter-plan-mode.ts` | LLM 调用进入模式（免审批）。工具 description（enter-plan-mode.md）写明触发条件：新功能/多方案/多文件/需求不清 → 进 plan mode；单行修复/纯研究 → 不进 |
| 出口工具 | `tools/builtin/planning/exit-plan-mode.ts` | 退出 + 把计划呈现给用户审批；支持最多 3 个方案选项 |
| 守卫 | `permission/policies/plan-mode-guard-deny.ts` | **硬强制**：plan mode 激活时，Write/Edit 只能写计划文件，否则 `kind: 'deny'`（工具不执行）；TaskStop/CronCreate/CronDelete 也 deny |

辅助：`exit-plan-mode-review-ask.ts` —— 退出审批（approve/cancel/reject/revise）；`plan-mode-tool-approve.ts` —— 进入免审批、计划文件写入自动放行。

**核心逻辑一句话**：状态机持有"是否在规划中" → 两个工具负责进出 → 守卫保证规划期间只能读 + 写计划文件 → 退出时用户审批。

### 0.3 Hermes 现状：软约束（已知局限，辅助参考）

Hermes 的规划/技能体系**全部是提示词工程，无代码强制**：

- 技能索引：`prompt_builder.py:1716` 注入 `<available_skills>` 块（只有名字+描述），配文字 "you MUST load it with skill_view(name)"——MUST 只是语气，没有执行层
- 按需加载：`tools/skills_tool.py:961` skill_view 把 SKILL.md 全文**作为普通文本**放进消息历史，不是特权层
- **约束失效场景**（用户指出，代码佐证）：
  1. 模型不调 skill_view → skill 约束为零（无任何代码要求它加载）
  2. 上下文压缩可能处理/挤掉技能块（`context_breakdown.py:15` 有专门正则处理 available_skills 块）
  3. 长对话衰减后模型"忘记"指令
  4. 用户指令与 skill 冲突时，模型倾向服从用户
- 结论：**Hermes 的 plan skill / todo 是纯软方案，可靠性依赖模型质量**。这正是 V2 需要"硬守卫"（plan mode）的动机。

---

## 1. 设计原则（贴合 V2 架构）

1. **骨架零改动**：conversation_loop.py 不动——plan 工具就是普通工具，循环天然支持
2. **扩展 > 新建**：守卫检查点复用 tool_runner 的执行链，不另起炉灶
3. **注入靠工具描述**：Kimi 把触发条件写在 EnterPlanMode 的 description 里，V2 照做——零 prompt 改动
4. **教学可见**：每个文件头注明 Hermes/Kimi 对应（V2 惯例）

## 2. 三档方案

### 方案 A：软规划（~40 行）——理解铺垫用

- 不加状态机。一个 `plan` 工具（把计划写入 `~/.minimal-agent-v2/plans/xxx.md`）+ system prompt 一句"复杂任务先规划"
- 本质 = Hermes plan skill 的 Python 版，纯提示词工程
- **局限**：模型可跳过规划直接干；写计划后也无强制"按计划执行"（0.3 的全部失效场景都在）

### 方案 B：核心 Plan Mode（~130 行）★ 推荐先做这个

**新增 `plan_mode.py`**：
- `PlanMode` 类：`is_active` / `plan_id` / `plan_path`，enter()/exit()（镜像 Kimi PlanMode）
- 模块级单例 + 计划文件 `~/.minimal-agent-v2/plans/{id}.md`
- `plan_guard(name, args)`：plan mode 激活时，`write` 只允许写计划文件，否则返回拒绝原因（镜像 Kimi plan-mode-guard-deny）
- 两个 `@tool`：
  - `enter_plan_mode()`：进入 + 返回工作流提示（调研 → 写计划 → exit）
  - `exit_plan_mode()`：退出，开始执行

**改 `tool_runner.py`（~10 行）**：`ToolRunner.__init__` 加 `guard` 属性；`execute()` 在参数解析后、执行前检查：
```python
if self.guard is not None:
    reason = self.guard(fn_name, fn_args)
    if reason:
        return {"role": "tool", "tool_call_id": tool_call_id,
                "content": f"错误：{reason}"}   # 工具不执行，错误回填
```

**改 `cli.py`（~2 行）**：`import plan_mode`（触发 @tool 注册）+ `runner.guard = plan_guard`

效果：用户给复杂任务 → 模型（读工具描述）主动 enter_plan_mode → 只读调研 + 写计划文件 → exit_plan_mode → 开始执行；规划期间任何 write 非计划文件被守卫拒绝（硬约束）。

### 方案 C：完整版（B + ~200 行）——产品级

- exit_plan_mode 时 **CLI 审批**：展示计划 → 用户输入 approve / revise+反馈（镜像 Kimi exit-plan-mode-review-ask）
- **多方案选项**：exit 时模型可带 1-3 个方案，用户选一个执行（镜像 Kimi options）
- **动态重规划**：执行中模型可再进 plan mode 或直接改计划文件（文件即计划，天然支持）
- 用户中断：CLI 输入 `!plan` 随时进入规划模式

## 3. V2 接入点汇总（已盘点现有代码）

| 文件 | 改动 | 行数 |
|------|------|------|
| `plan_mode.py`（新建） | PlanMode 类 + guard + 两个工具 | ~120 |
| `tool_runner.py` | execute() 加 guard 检查点 | ~10 |
| `cli.py` | import 触发注册 + guard 注入 | ~2 |
| `conversation_loop.py` | **零改动**（工具调用已是循环一部分） | 0 |

## 4. 演进路线

```
方案 A（软，理解铺垫）→ 方案 B（核心，先做）→ 方案 C（完整，产品级）
```

建议直接做 B：它覆盖用户核心诉求"用户提出任务 → agent 规划 → 执行"，且只动一个文件 + 两个小改动。

## 5. 分支与仓库注意事项

- 开分支名：`plan-mode`（或 `plannable`，用户定）
- ⚠️ V2 当前在 skills-framework 分支，工作区有 conversation_loop.py 1 行未提交改动（疑似用户/他会话的）——开分支前需确认该改动归属
- 提交用 conventional commits（feat:）

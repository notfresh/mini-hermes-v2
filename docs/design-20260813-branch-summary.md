# 分支总结：skills-framework / plan-mode-v1 / plan-mode-v2

> 三个功能分支的改动清单与特性对比。写于 2026-08-13，基于各分支相对 main 的提交历史。
> 用途：快速了解每个分支做了什么、带来什么能力、分支之间的关系。

---

## 1. 分支拓扑（重要：是线性继承，不是并列）

```
main（五模块基线，5 commits）
└── skills-framework   +3 commits   技能框架：挂载 Superpowers + 内容外置 + 扩展协议草案
    └── plan-mode-v1   +4 commits   软规划：Plan Mode V1（纯提示词）+ hard-vs-soft demo 移入
        └── plan-mode-v2  +1 commit 硬规划：Plan Mode V2（状态机 + 守卫）
```

**plan-mode-v1 包含 skills-framework 的全部改动，plan-mode-v2 又包含前两者的全部改动。**
三个分支不是各干各的平行方案，而是同一主线上逐层叠加的三个阶段。

## 2. skills-framework 分支（+3 commits）

### 2.1 改动清单

| 提交 | 内容 | 改动面 |
|---|---|---|
| `40edb7a` feat: 挂载 Superpowers 技能框架 | skill_registry.py（117 行）+ bootstrap_injector.py（116 行）+ 4 个 SKILL.md（using-superpowers / brainstorming / systematic-debugging / verification-before-completion）+ load_skill 工具 | 14 文件，+870 行 |
| `fc540a2` refactor: 技能内容外置 | **删除** bootstrap_injector.py 与 skills/ 目录；conversation_loop 改为"约定检测"注入（技能包自带 using-superpowers 才注入）；cli 只留 `--skills-dir` / `--no-skills` | 10 文件，-422 行 |
| `156a31d` docs: 扩展协议设计草案 | docs/extension-protocol.md（205 行）：四层扩展模型（Plugin/Tool/Skill/MCP/Command）+ manifest + 注册表设计 | +205 行 |

### 2.2 带来的特性

**V2 获得"技能框架"能力（三件套）**：

1. **技能文件**：SKILL.md + frontmatter（name/description），行为塑形提示词
2. **启动注入**（灵魂）：会话开始时，技能索引 `<available_skills>` 与"技能总开关"（using-superpowers 全文）拼进 system[0]，免疫上下文压缩丢消息；注入带 origin 标记，会话恢复不重复注入（`_bootstrap_injected` 标记 + 消息 origin 双重去重）；发 API 前由 llm_client `_strip_origin` 剥离内部标记
3. **工具映射**：`load_skill` @tool，模型按需加载技能全文

**`fc540a2` 内容外置是关键转折**：V2 不再内置任何技能内容，只保留通用插口——宿主 = 插口，内容 = 外置技能包（如 minimal-superpowers）。技能包可单独分发、单独替换；不挂技能包时 `--no-skills` 一键回退为原版行为。

**`156a31d`** 把插口泛化为四层扩展协议的路线图（Skill → Tool/MCP/Command/Plugin），是二期蓝图。

## 3. plan-mode-v1 分支（+4 commits，含 skills-framework 全部）

### 3.1 改动清单

| 提交 | 内容 | 改动面 |
|---|---|---|
| `e06c040` feat: Plan Mode V1 — 纯提示词规划 | plan_mode.py（69 行）：`PLAN_GUIDANCE` 全文（工具 description）+ `plan` 工具（写计划到 `~/.minimal-agent-v2/plans/plan-<ts>.md`）；turn_context system prompt 追加规划规则；cli import 注册工具 | 4 文件，+191 行 |
| `a9d6563` docs: bootstrap 注释修正 | conversation_loop.py 一行注释 | ±1 行 |
| `155a7d1` chore: 清理示例 | 删除 tang_poems/ 三个测试文件 | -15 行 |
| `32c4e45` feat: hard-vs-soft-mode 移入 | hard-vs-soft-mode/ 五文件（README + agent_core + hard_mode + soft_mode + models），从 V1 移入 | +224 行 |

### 3.2 带来的特性

**Plan Mode V1 = 软约束规划（提示词层面）**：

- 模型接到复杂任务（多步骤/多文件/需设计决策）→ 先调用 `plan` 工具写计划文件，再执行
- 计划格式强制：每阶段必须同时含**目标 + 验收条件**（可执行、可验证的完成标准，用户明确要求）
- 执行规则：每完成一阶段先对照验收条件验证，不满足则修正；全部完成后做**整体验证**（逐条核对全部验收条件）
- 无状态机、无守卫——约束全靠提示词，可靠性依赖模型自觉。这是理解"软约束边界"的铺垫版

**hard-vs-soft-mode**：Hello World 级对比 demo（零依赖、模拟模型），用"乖/叛逆"两种模型 × 软/硬两种模式，直观展示"软 = 提示词约定（守不守取决于模型）；硬 = 代码强制（谁来了都得守）"——Plan Mode 两版演进的教学脚手架。

## 4. plan-mode-v2 分支（+1 commit，含前两者全部）

### 4.1 改动清单

| 提交 | 内容 | 改动面 |
|---|---|---|
| `350ef8b` feat: Plan Mode V2 — 状态机 + 守卫 | plan_mode.py 重写（171 行）：`PlanMode` 类（is_active / plan_path / enter / exit）+ `plan_guard` 守卫 + `enter_plan_mode` / `exit_plan_mode` 工具；tool_runner.py 加 guard 检查点；cli 注入 `runner.guard = plan_guard`；turn_context 调整 | 5 文件，+181/-51 行 |

### 4.2 带来的特性

**Plan Mode V2 = 硬约束规划（代码强制）**，对应 Kimi plan-mode-guard-deny：

- **状态机**：`PlanMode` 类维护规划模式激活状态（is_active）与计划文件路径（plan_path）；`enter_plan_mode` / `exit_plan_mode` 工具进出规划模式
- **守卫**：`plan_guard(name, args)` — 规划模式激活时，`write` 工具只允许写计划文件，写其他文件返回 DENIED（工具不执行，模型收到错误结果，不能自我合理化）
- **挂载方式**：ToolRunner 增加 `guard` 检查点（execute 内、工具执行前，None = 不检查），由 CLI 注入——**conversation_loop 零改动**
- **V1 → V2 演进关系**：V1 的提示词规则保留为引导，V2 在其上叠加代码级强制；V2 继承 V1 的验收条件/阶段验证/整体验证设计

## 5. 特性叠加总览

| 能力 | main | skills-framework | +plan-mode-v1 | +plan-mode-v2 |
|---|---|---|---|---|
| 五模块核心循环（会话/工具/LLM/消息） | ✅ | ✅ | ✅ | ✅ |
| 技能框架（启动注入 + load_skill + 外置技能包） | — | ✅ | ✅ | ✅ |
| 扩展协议设计蓝图（文档） | — | ✅ | ✅ | ✅ |
| 软规划（plan 工具 + 验收条件提示词） | — | — | ✅ | ✅ |
| hard-vs-soft 对比 demo | — | — | ✅ | ✅ |
| 硬规划（状态机 + 守卫，违规 DENIED） | — | — | — | ✅ |

**最终形态 = plan-mode-v2 分支**：技能框架 + 软规划 + 硬规划 + 教学 demo 全部就位，且 conversation_loop 核心循环始终零改动（新能力全部作为可选参数/新模块注入，None = 原版行为）。

## 6. 状态与后续

- 三个分支均**未合入 main**（main 仍为五模块基线 + REPL/-i/session_manager 基础提交）
- Plan Mode V3 待办（见 docs/design-20260812-plan-mode.md）：exit 审批（approve/revise）、多方案选项、!plan 动态重规划
- 扩展协议二期（docs/extension-protocol.md）：Tool/MCP/Command/Plugin 全类型 + 分发形态
- 已知问题：上下文超长时 API 报 tool 消息结构错位——疑似 message_store.compress_if_needed 压缩后 tool 消息丢失前置 tool_calls（规划模式密集 read 会放大）

# MinimalAgent V2 — Plan Mode 实现报告

日期：2026-08-17（实现 08-12 ~ 08-13，08-17 补 slash 命令与归档）
范围：从"V2 缺 task scheduler"出发，调研 → 方案 → 三版实现 → 实战验证
分支：plan-mode-v1 / plan-mode-v2（本报告归档于 plan-mode-v2）

---

## 1. 任务起源：一次认知纠偏

用户提出"V2 缺一个 task scheduler"，最初的理解是"管线程/公共资源的调度"。
调研后发现 **"Task Scheduler" 在三个语境下是三个东西**：

| 语境 | 含义 | 代表 |
|------|------|------|
| 操作系统 | 线程/进程调度，管 CPU 时间片 | 用户最初的直觉 |
| agent 框架 | **定时任务**调度（时间驱动） | Hermes cron/scheduler.py |
| 任务规划 | **多阶段任务拆解**（任务驱动） | plan-and-execute / Plan Mode |

结论：V2 缺的不是调度器，是"任务拆解 + 进度跟踪 + 规划约束"。
另：Fornax 为口误（实际是字节 AI Agent Ops 平台：Prompt 即服务 + RAG + 观测 + 评测，
与任务调度无关）；GitHub 上同名项目（静态站生成器等）也都不相关。

## 2. 调研结论（Kimi Code 为参照物）

**技术栈**：TypeScript monorepo（Node.js 生态，pnpm workspace，Node >= 24）。

**Plan Mode 核心逻辑 = 四件套**（packages/agent-core）：
1. `PlanMode` 状态机（agent/plan/index.ts）：`is_active` / `plan_id` / `plan_file_path`，enter/exit/cancel
2. `EnterPlanModeTool`：进入（免审批）；触发条件写在工具 description 里
3. `ExitPlanModeTool`：退出 + 计划呈现给用户审批（支持 1-3 个方案选项）
4. `PlanModeGuardDenyPermissionPolicy`：**硬守卫**——plan mode 激活时 Write/Edit 只能写计划文件，否则 deny；TaskStop/CronCreate/CronDelete 也 deny

**Hermes 现状（软约束，已知局限）**：skill 体系 = 纯提示词工程——
`<available_skills>` 索引（prompt_builder.py:1716）+ skill_view 按需加载（文本进消息历史）。
"you MUST load it" 只是语气，无执行层；约束失效场景：模型不加载 / 压缩挤掉技能块 /
长对话遗忘 / 用户指令覆盖。

## 3. 核心认知：软 vs 硬

- **软（提示词约定）**：规则是文本，模型自觉遵守。可靠性依赖模型质量。
- **硬（代码强制）**：状态在框架内存（模型无法"忘记"），每次工具调用先过守卫，
  违规返回 DENIED、工具不执行。可靠性从模型转移到 harness（有成本）。

判断标准（试金石）：**"改代码能实现"的能力 = harness 范畴（agent 框架学习范围）；
"只能靠换更强模型"的 = 模型范畴**。任务规划/多阶段/权限控制全是 harness 工程。

用户自悟的架构洞察（与业界一致）：
**静态规划 → 动态重规划 → 自我反思 → 人类介入** 四档。
对应：plan-then-execute / ReAct / Reflexion / human-in-the-loop。

## 4. 三版递进实现

### V1（plan-mode-v1，软）：纯提示词规划
- `plan` 工具（写计划到 ~/.minimal-agent-v2/plans/）+ system prompt 规划规则
- 提示词增强（用户要求）：每个阶段必须含 **目标 + 验收条件**；完成时**阶段验证 + 整体验证**
- 实测：模型主动调 plan → 写带验收条件的计划 → 按阶段执行 → 发现浮点精度问题修复 → 整体验证 ✅

### V2（plan-mode-v2，硬）：状态机 + 守卫
- `PlanMode` 状态机 + `enter_plan_mode` / `exit_plan_mode` 工具（Kimi 对齐）
- `plan_guard` 守卫 + ToolRunner 检查点：规划期 write 只能写计划文件
- 改动：plan_mode.py 重写 / tool_runner.py +13 / cli.py 注入 / turn_context.py 规则更新
- 实测证据（黄金场景）：REPL 中 `/plan` 后模型直接尝试写业务文件 →
  **🚫 守卫 DENIED** → 模型读错误后自动调 exit_plan_mode → 正常执行 ✅
  守卫单测 6 场景全过；开放任务"CSV 解析工具"完整闭环（enter → 调研 → 写计划 → exit → 执行 → 验证 completed）

### slash 命令（补丁，08-17）
- `/plan`：用户手动进入规划模式（人类介入入口，方案 C 的雏形）
- `/run`：退出规划模式
- 注：此提交最初误落 agent-ignore 分支，已 cherry-pick 归位 plan-mode-v2（764de33）

## 5. 已知问题与边界

1. **上下文超长**：`Messages with role 'tool' must be a response to a preceding message with 'tool_calls'`
   ——疑似 MessageStore.compress_if_needed 压缩后结构错位，规划模式密集调研会放大。排查方向：message_store.py。
2. **bash 可绕守卫**：守卫只拦 write 工具，bash 不拦（与 Kimi 一致："Bash follows normal permission mode"）。
   教学版已知简化边界，真实系统在 shell 层补防。
3. **简单任务模型跳过规划**：正确行为（enter 工具描述明确"不适用简单任务"），非缺陷。

## 6. 仓库状态（08-17 盘点）

- plan-mode-v2：Plan Mode V2 完整 + slash 命令（764de33）+ 用户后续改动（uv 依赖、merge v1、tool repeat interception 设计）
- plan-mode-v1：V1 实现 + uv 依赖管理
- agent-ignore：用户新分支（AgentIgnore 路径权限校验）——与 plan mode 无冲突
- main：用户的三分支总结文档
- 工作区干净

## 7. 方法论沉淀（值得记录）

1. **先调研后方案**：实现前先读参照物源码（Kimi 四件套），方案基于真实代码而非想象
2. **先讨论后动手**：三版递进方案让用户选方向，确认后再写代码
3. **扩展前盘点现有模块**：V2 的窄腰骨架 + 模块委托决定了改动面（conversation_loop 零改动）
4. **提示词质量 = 验收条件 + 完成验证**：让"完成"有可判定的标准
5. **硬约束的落点**：守卫检查点在工具执行前（ToolRunner.execute），模型收到错误后能自我纠正
6. **git 操作前必须确认分支**：08-17 教训——多会话并行操作下，提交前先 `git branch --show-current`，否则提交会落错分支

# MinimalAgentV2 — 五模块拆分的 Agent 框架

从 Hermes Agent 核心循环（`agent/conversation_loop.py`，5194 行）剥离的教学级框架。
V2 在 V1 基础上按"5 模块拆分"重构：核心骨架保持 ~30 行，防御逻辑全部下沉到模块。

## 与 Hermes 的对照

| V2 模块 | 文件 | Hermes 对应 |
|---------|------|-------------|
| `ConversationLoop`（骨架） | conversation_loop.py | agent/conversation_loop.py :: run_conversation（5194 行） |
| `TurnContext` | turn_context.py | agent/turn_context.py + agent/prompt_builder.py |
| `LoopController` | loop_controller.py | agent/iteration_budget.py + 循环退出条件 |
| `LLMClient` | llm_client.py | agent/chat_completion_helpers.py（重试/退避/错误分类） |
| `ToolRunner` | tool_runner.py | tools/registry.py + agent/tool_executor.py |
| `MessageStore` | message_store.py | 循环内 messages 操作（压缩/快照/持久化） |
| 内置工具 | tools.py | tools/file_tools.py + tools/terminal_tool.py |
| CLI | cli.py | cli.py main() |

## 核心骨架（conversation_loop.py :: ConversationLoop.run）

```python
while self.controller.should_continue():          # 还继续吗？→ LoopController
    response = self.llm.complete(messages.all())  # 发请求 → LLMClient（重试在内）
    assistant = normalize_assistant_message(...)
    if assistant.get("tool_calls"):
        results = self.tools.execute_all(...)     # 执行 → ToolRunner
        for r in results: messages.append(r)      # 回填 → MessageStore
        continue
    return self._success_result(...)              # 无工具调用 → 最终回答
```

## 五模块各自回答的问题

1. **LoopController** — "还继续吗？"（轮数/预算/中断/grace）
2. **LLMClient** — "模型说什么？"（重试/退避/错误分类，调用方看不到）
3. **ToolRunner** — "工具结果是什么？"（查找/解析/防御/回填）
4. **MessageStore** — "消息放哪/太长怎么办？"（增删改查/压缩）
5. **TurnContext** — "回合开始前准备什么？"（系统提示词/清洗/凭证预检）

## 使用

```bash
# 列工具
python3 cli.py --list-tools

# 单轮提问
export DEEPSEEK_API_KEY=sk-xxx
python3 cli.py "现在几点？"

# 触发工具调用（会走 核心循环 → ToolRunner → 回填 → 再问）
python3 cli.py "计算 (123+456)*2，然后读取 /etc/hostname"

# 详细调试
python3 cli.py -v "列出当前目录"

# 技能框架模式（默认开启，--no-skills 可关闭）
python3 cli.py "Let's make a react todo list" -v   # 看它是否先走 brainstorming
```

## 技能框架挂载（skills-framework 分支）

在 V2 五模块上挂载了 Superpowers 技能框架（蒸馏自 obra/superpowers + kimi-code + Hermes）：

| 新增组件 | 文件 | 参考来源 |
|---|---|---|
| 技能注册表 | skill_registry.py | Hermes tools/skills_tool.py + prompt_builder.py:1490 |
| 启动注入器 | bootstrap_injector.py | kimi-code agent/injection/injector.py（DynamicInjector 39行）+ plugin-session-start.ts |
| load_skill 工具 | tools.py | Hermes skill_view |
| 技能库 | skills/*/SKILL.md | superpowers-plus skills/（18→4 个） |

**挂载点**（改动最小化，五模块骨架不动）：
- `TurnContext.build_initial_messages`：技能索引（`<available_skills>` 块）+ 技能总开关全文拼进 system prompt
- `ConversationLoop.__init__/run`：可选 `skills` 参数；回合准备段构建 bootstrap（只注入一次）
- `llm_client.complete`：发送前剥离内部 `origin` 标记（会话恢复检测用）

**两种注入方式都实现了**（教学对比）：
1. **Superpowers 式**：注入"技能总开关"全文（`<EXTREMELY_IMPORTANT>` + 1% 规则 + Red Flags）→ 强制模型先查技能
2. **Hermes 式**：注入技能索引列表（name + description）→ 信任模型自主判断

**去重设计**（来自 kimi 源码）：`injected_at` 标记 + 消息里 `origin.kind == "injection"` 检测（会话恢复场景），压缩/清除后重置。

## 传承关系

- V1（minimal-agent/）：单文件 `agent_loop()`，核心循环 + 工具 + CLI 都在一个函数里
- V2（本目录）：五模块拆分，骨架 30 行，防御下沉
- 相同点：@tool 装饰器、内置工具集、CLI 参数、DeepSeek 优先

## 扩展方向（对应 Hermes 进阶机制）

- [ ] 流式输出（Hermes: _interruptible_streaming_api_call）
- [ ] 并发工具执行（Hermes: _execute_tool_calls_concurrent）
- [ ] 凭证自动轮换（Hermes: _ensure_runtime_credentials）
- [ ] 上下文 LLM 摘要压缩（Hermes: context_compressor）
- [ ] 记忆读写（Hermes: memory_manager）
- [ ] 子代理分发（Hermes: delegate_tool）

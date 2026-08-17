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

# 技能框架模式（挂载外部技能包 minimal-superpowers）
python3 cli.py --skills-dir ../minimal-superpowers/skills "Let's make a react todo list" -v
```

## 技能框架插口（skills-framework 分支）

V2 作为宿主提供**通用技能插口**（对应 Hermes 的 `skills.external_dirs` + `skill_view` 工具），
技能内容完全外置——独立的 [MinimalSuperPowers](https://github.com/ 技能包
（蒸馏自 obra/superpowers + kimi-code）通过 `--skills-dir` 挂载：

```bash
git clone <minimal-superpowers-url> ../minimal-superpowers   # 单独下载技能包
python3 cli.py --skills-dir ../minimal-superpowers/skills "Let's make a react todo list"
```

**宿主约定**（对应 Superpowers 的 invariants）：
1. 挂载的技能目录注入 `<available_skills>` 索引（Hermes 式：只列 name+description）
2. 技能包自带 `using-superpowers` 时，会话开始自动注入总开关全文
   （Superpowers 式：`<EXTREMELY_IMPORTANT>` + 1% 规则 + Red Flags）——只注入一次
3. `load_skill` 工具按需加载技能全文（对应 Hermes `skill_view`）

**插口实现**（五模块骨架不动）：
- `TurnContext.build_initial_messages`：接收技能索引 + 总开关全文，拼进 system prompt
- `ConversationLoop`：可选 `skills` 参数；`_build_bootstrap()` 约定检测 + 注入去重
- `skill_registry.py`：扫描外部目录 + frontmatter + `has_bootstrap()` 检测
- `llm_client.complete`：发送前剥离内部 `origin` 标记（会话恢复检测用）

**去重设计**（来自 kimi 源码）：`_bootstrap_injected` 标记 + 消息里
`origin.kind == "injection"` 检测（REPL 会话恢复场景），压缩/清除后重置。

不挂任何技能包 = V2 原版行为（`--no-skills` 也可显式关闭）。

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

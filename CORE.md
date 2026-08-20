# CORE — 核心档案

> 姊妹篇：`README.md` 讲「这是什么、怎么跑」；本文件回答更本质的问题——
> **核心是什么、从哪来、怎么来的。**
>
> 一句话：MinimalAgentV2 是 Hermes 核心思维的最小完整继承 —— 不是简化玩具，而是从
> 15 万行生产级代码里提取出来的、可运行可扩展的执行模型。

---

## 1. 核心执行模型：30 行

Agent 的本质只有三个词：**LLM + Tools + Loop**。MinimalAgentV2 的核心骨架
（`conversation_loop.py :: ConversationLoop.run`）完整复刻了 Hermes 主循环：

```python
while self.controller.should_continue():          # ① 还继续吗？→ LoopController
    response = self.llm.complete(messages.all())  # ② 发请求 → LLMClient（重试在内）
    assistant = normalize_assistant_message(...)
    if assistant.get("tool_calls"):
        results = self.tools.execute_all(...)     # ③ 执行 → ToolRunner
        for r in results: messages.append(r)      # ④ 回填 → MessageStore
        continue
    return self._success_result(...)              # ⑤ 无工具调用 → 最终回答
```

循环只有 5 个动作：**问模型 → 模型要调工具？→ 执行 → 回填 → 再来一轮**。
当模型不再请求工具时，循环收敛，返回最终回答。

所有防御（重试、退避、错误分类、凭证预检、权限校验……）都在主链**之外**——
这也是为什么骨架能保持 30 行。

## 2. 五模块：谁回答什么问题

模块划分不是拍脑袋，每个模块都能在 Hermes 源码中找到一一对应的「原主」：

| V2 模块 | 回答的问题 | Hermes 对应（源码） |
|---------|-----------|---------------------|
| `ConversationLoop` | 循环主链怎么走？ | `agent/conversation_loop.py :: run_conversation`（5194 行） |
| `LoopController` | 还继续吗？轮数/预算/中断/grace | `agent/iteration_budget.py` + 循环退出条件 |
| `LLMClient` | 模型说什么？重试/退避/错误分类 | `agent/chat_completion_helpers.py` |
| `ToolRunner` | 工具结果是什么？查找/解析/防御/回填 | `tools/registry.py` + `agent/tool_executor.py` |
| `MessageStore` | 消息放哪、太长怎么办？增删改查/压缩 | 循环内 messages 操作 |
| `TurnContext` | 回合开始前准备什么？系统提示词/清洗/凭证预检 | `agent/turn_context.py` + `agent/prompt_builder.py` |

## 3. 蒸馏方法论：怎么从 5194 行里剥出 30 行

这不是「删掉冗余」，而是**逐层剥离后重新论证**。四步：

1. **入口定位** — 在 15 万行里找到执行核心：
   `agent/conversation_loop.py :: run_conversation`（5194 行，全仓库最长的单函数之一）。
2. **主链剥离** — 只保留「让 agent 工作」的循环主链：5 个动作、30 行。
3. **防御下沉** — 把 ~4300 行防御（重试/退避/凭证轮换/并发执行/上下文压缩/中断钩子……）
   按职责挪进各模块，循环本身保持干净 —— **「防御是『怎么不死』，核心是『怎么活』」**。
4. **对照验证** — 逐模块回 Hermes 源码核对：每个设计都有出处、每个命名都有原主，
   保证「继承」而非「凭空发明」。

## 4. 账目：砍掉的 85% 是什么

```
Hermes run_conversation      5194 行（conversation_loop.py:588~5781）
MinimalAgentV2 全仓库源码   ~2467 行（12 个模块，含注释）
核心循环                      30 行
```

**关键结论：砍掉的不是「功能」，是「防御」。**

V2 保留了所有「让 agent 工作」的核心；砍掉的 4300 行几乎全是「让 agent 在真实世界
不崩」的防御——而每一层防御背后，都是一个真实事故（key 过期、provider 挂掉、
上下文超长、用户打断、工具出错……）。

| 层 | Hermes | V2 | 砍掉的代表 |
|----|--------|----|-----------|
| API 层 | ~1500 行 | ~80 行 | 凭证自动轮换、provider fallback、流式输出、SDK 重试定制 |
| 上下文压缩 | ~400 行 | ~20 行 | LLM 摘要压缩、413 处理、压缩重试 |
| 工具层 | ~300 行 | ~120 行 | 并发执行、工具鉴权、工具护栏、子代理分发 |
| 中断/steer/钩子 | ~2000 行 | ~40 行 | /steer 中途改方向、插件钩子、记忆审查、技能 nudge |

逐项明细见 [`v2.WHAT-WAS-DISCARDED.md`](v2.WHAT-WAS-DISCARDED.md)。

## 5. 从 V2 长回 Hermes：路线图即防御清单

README 里的扩展方向，每一项勾选 = 亲手重建一层 Hermes 的真实防御：

```
[ ] 流式输出          ← Hermes: _interruptible_streaming_api_call
[ ] 并发工具执行      ← Hermes: _execute_tool_calls_concurrent
[ ] 凭证自动轮换      ← Hermes: _ensure_runtime_credentials
[ ] LLM 摘要压缩      ← Hermes: context_compressor
[ ] 记忆读写          ← Hermes: memory_manager
[ ] 子代理分发        ← Hermes: delegate_tool
```

这就是从「看懂」到「能写」的路。

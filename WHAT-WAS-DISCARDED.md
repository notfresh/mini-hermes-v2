# What Was Discarded — V2 相比 Hermes 砍掉了什么

> MinimalAgentV2 对照 Hermes 核心循环（`agent/conversation_loop.py` :: run_conversation，5194 行）的"丢弃清单"。
> 目的：让你在读 V2 代码时，清楚知道**哪些是故意没有的**，以及为什么。

---

## 一、账目对比

```
Hermes run_conversation    5194 行（conversation_loop.py:588~5781）
MinimalAgentV2 全部代码    1229 行（8 个文件，含注释）
V2 纯代码                  862 行（去掉注释/空行/docstring）

砍掉了约 85%。
```

**关键结论：砍掉的不是"功能"，是"防御"。**

V2 保留了所有"让 agent 工作"的核心（862 行）；砍掉的 4300 行几乎全是
"让 agent 在真实世界不崩"的防御——每一层防御背后都是一个真实事故。

---

## 二、逐项丢弃清单

### ① API 层：~1500 行 → ~80 行（砍 95%）

**丢弃：**
- **凭证自动轮换**（API key 过期自动换新）— V2 只查 key 存在不存在
- **provider fallback**（DeepSeek 挂了自动切 Anthropic）— V2 挂了就报错
- **流式输出**（逐 token 显示，可中断）— V2 一次性等完整响应
- **thinking 超时专门处理**（打印 3 条解决方案的分支）— V2 只有笼统 timeout
- **SDK 重试策略定制**（max_retries=0 + 自有重试）— V2 保留，但简化

**保留：** 基本重试 + 指数退避 + 错误分类（timeout/rate_limit/auth/bad_request/server/unknown）

### ② 上下文压缩：~400 行 → ~20 行（砍 95%）

**丢弃：**
- **LLM 摘要压缩**（让模型把旧对话总结成摘要，保留语义）
- 压缩重试、压缩次数上限
- 413 请求太大处理
- 压缩后仍超长的最终兜底

**保留：** 超长检测 + 截断动作（`MessageStore.compress_if_needed`）— 概念对，手段粗暴（直接丢中间消息）

### ③ 工具层：~300 行 → ~120 行（砍 60%）

**丢弃：**
- **并发执行**（多个独立工具同时跑，线程池）
- **工具鉴权**（敏感操作需要用户批准）
- **工具护栏**（哪些工具危险、谁能调）
- **子代理分发**（delegate 给其他 agent 实例）
- **工具执行超时控制**

**保留：** @tool 装饰器、查找/解析/执行/回填、错误回填给 LLM（错误也是 Observation）

### ④ 中断 / steer / 钩子：~2000 行 → ~40 行（砍 98%）

**丢弃：**
- **/steer 中途改方向**（模型思考时插入指令，下一轮生效）
- **step_callback / 插件钩子**（gateway 事件、插件扩展点）
- **记忆审查**（每回合读记忆、决定是否写记忆）
- **技能 nudge**（提示 agent 用 skill）
- **credit 通知**、MoA（多模型聚合）、codex 模式、多 transport 分发

**保留：** `LoopController.request_interrupt()`（中断标志 + 循环顶部检查）

### ⑤ 完全没碰的（V2 完全没有）

- **多 provider 适配**（anthropic / bedrock / codex / moa 四个 transport）— V2 只认 OpenAI 兼容
- **会话持久化**（session JSON、断点续聊）— V2 内存里跑完就没了
- **预算的多维消耗**（如 #77305：API 失败也扣预算饿死 fallback 链）— V2 只有按轮扣分
- **上下文引擎 / 外部记忆**（context_engine、ext-memory）— V2 无

---

## 三、为什么砍：教学 vs 生产

| 场景 | 需要什么 |
|------|---------|
| 教学环境（模型正常、网络正常、key 有效、对话不长） | V2 的 862 行就够 |
| 生产环境（模型抽风、网络抖动、key 过期、对话超长、用户打断、provider 挂掉） | 每一行防御都是为一种"事故"准备的 |

**教学版的价值**：把"agent 到底在做什么"从 5000 行防御里剥离出来，
让你 30 分钟看懂核心。防御是"怎么不死"，核心是"怎么活"。

---

## 四、从 V2 长回 Hermes 的路线图

README 里的扩展方向，其实每一勾都是一层被丢弃的防御：

```
[ ] 流式输出          ← Hermes: _interruptible_streaming_api_call
[ ] 并发工具执行      ← Hermes: _execute_tool_calls_concurrent
[ ] 凭证自动轮换      ← Hermes: _ensure_runtime_credentials
[ ] LLM 摘要压缩      ← Hermes: context_compressor
[ ] 记忆读写          ← Hermes: memory_manager
[ ] 子代理分发        ← Hermes: delegate_tool
[ ] 多 provider 适配  ← Hermes: agent/transports/*
[ ] 会话持久化        ← Hermes: session JSON + checkpoint
```

每个勾选后，你都会亲手重建一层 Hermes 的真实防御——
这就是从"看懂"到"能写"的路。

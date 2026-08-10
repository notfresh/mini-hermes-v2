# MinimalAgentV2 多任务并发设计文档（草案 v0.2）

> 状态：**讨论稿，未实现**（用户要求先讨论方案）
> 基线：V2.0（tag v2.0，五模块拆分）
> 设计依据：001study/hermes-concurrency-isolation-report.md（Hermes 并发机制调查）
> v0.2 修订：吸收讨论结论——**不新增 session_registry/session_store**，延续升级现有 session_manager.py（它已承担 Session CRUD + 持久化）；只新增 task_scheduler.py 一个模块。

---

## 1. 背景与目标

V2.0 是单会话框架：一个 CLI 进程 = 一个 ConversationLoop = 一个会话。
本设计的目的是让 V2 支持**多个任务同时运行、互不干扰**，同时保持教学级骨架（核心循环 ≤30 行）和「每个模块只做一件事」的拆分原则。

目标场景（举例）：
- 同时跑 3 个 cron 式定时任务（早报、刷题、监控），互不串话
- 一个任务失败/崩溃，不影响其他任务
- 任务可以中途查看进度、单独终止

非目标：
- 不做分布式、不做多进程（单进程线程池够教学用）
- 不做 Hermes 那种 gateway 多平台接入

---

## 2. 从 Hermes 学到的五个模式（设计依据）

| # | Hermes 模式 | 源码证据 | V2 对应 |
|---|------------|---------|---------|
| 1 | **实例隔离优先**：每会话独立 agent 实例，可变状态全在实例内 | gateway/run.py:63-68（LRU 缓存每会话实例） | 每任务独立五模块实例 |
| 2 | **存储按会话分家**：messages 外键归属 | hermes_state.py:762/812 | **现有方案已是文件级分家**（每会话一个 JSON 文件） |
| 3 | **env 陷阱**：进程全局变量必须串行化 | cron/scheduler.py:3985-3992（顺序池） | 不用 env 传任务状态，用 contextvar |
| 4 | **上下文快照**：copy_context() 让每个任务在隔离上下文跑 | cron/scheduler.py:4025-4029 | 提交任务前 copy_context |
| 5 | **单写者 + WAL**：DB 写集中串行，读可并行 | scheduler.py:2838；hermes_state.py:10 | **教学级不需要**（每会话独立文件，无共享写） |

> 关键洞察：Hermes 用共享 SQLite（WAL + 单写者）是因为要**跨会话查询**（搜索/统计/计费/跨平台路由）。V2 没有这些需求，现有「每会话一个 JSON 文件」就是比 SQLite 更彻底的隔离——文件级隔离，零锁零竞争。

---

## 3. 总体架构

```
                    ┌─────────────────────────────┐
                    │      TaskScheduler          │
                    │  (ThreadPoolExecutor ×2)    │
                    │  并行池 / 顺序池            │
                    └──────────┬──────────────────┘
                               │ submit(copy_context)
              ┌────────────────┼─────────────────┐
              ▼                ▼                 ▼
        ┌────────────┐  ┌────────────┐   ┌────────────┐
        │ AgentSession A │ AgentSession B │ AgentSession C  ← 每任务一套五模块实例
        │ (五模块)   │  │ (五模块)   │   │ (五模块)   │   （内存隔离，天然）
        └─────┬──────┘  └─────┬──────┘   └─────┬──────┘
              │               │               │
              └───────────────┼───────────────┘
                              ▼
              ┌─────────────────────────────────────┐
              │  SessionManager（延续升级）           │
              │  - 注册表：session_id → AgentSession  │
              │  - CRUD + 生命周期（已有能力延续）      │
              │  - 存储：每会话独立文件（天然隔离）      │
              └─────────────────────────────────────┘
```

**模块划分（修订后）**：

1. **`task_scheduler.py`** —— 唯一新增模块：并发调度（双池 + 去重 + 上下文快照）
2. **`session_manager.py`** —— 延续升级（不新增）：Session 升级为持有五模块实例的 AgentSession；SessionManager 升级为注册表

---

## 4. 模块设计

### 4.1 session_manager.py —— 延续升级（吸收原 registry/store 职责）

现有能力（保留）：Session 类 CRUD、SessionManager 生命周期、每会话独立 JSON 文件持久化、REPL。

升级点：

```python
class AgentSession:
    """每个任务一个「房子」：持有自己的五模块实例 + 消息。"""
    def __init__(self, session_id: str):
        self.session_id = session_id
        # 每任务独立实例 —— 内存隔离的核心（无锁，结构性隔离）
        self.turn_context = TurnContext()
        self.controller = LoopController()
        self.llm = LLMClient()
        self.tools = ToolRunner()
        self.messages = MessageStore()
        self.status = "idle"          # idle / running / done / failed
        self.last_error: str | None = None

class SessionManager:
    """升级为多会话注册表。"""
    def __init__(self, base_dir: str = "~/.minimal-agent-v2"):
        self._sessions: dict[str, AgentSession] = {}   # 注册表
        self._lock = threading.Lock()                  # 仅保护注册表本身

    def create(self, session_id: str) -> AgentSession: ...   # CRUD 延续
    def get(self, session_id: str) -> AgentSession: ...      # CRUD 延续
    def delete(self, session_id: str) -> None: ...           # CRUD 延续
    def save(self, session: AgentSession) -> None: ...       # 每会话独立文件（延续）
```

教学点：
- **锁只保护注册表 dict 本身**（增删查改的原子性），**不保护 AgentSession 内部状态**——因为内部状态只被该任务自己的线程访问（结构性隔离）
- 这就是「给每个人一个房子，不要打架」：房子之间的门锁（注册表锁）很便宜，房子内部不需要锁

### 4.2 task_scheduler.py —— 双池 + 去重 + 上下文快照

```python
class TaskScheduler:
    def __init__(self, max_workers: int = 4):
        self._parallel_pool = ThreadPoolExecutor(max_workers, thread_name_prefix="task-")
        self._sequential_pool = ThreadPoolExecutor(1, thread_name_prefix="task-seq")
        self._running: set[str] = set()
        self._running_lock = threading.Lock()

    def submit(self, session_id: str, fn, *, serial: bool = False):
        # 1) 去重：同一 session 已在跑 → 跳过（或排队，可配置）
        with self._running_lock:
            if session_id in self._running:
                return None
            self._running.add(session_id)
        # 2) 上下文快照：每个任务在隔离的 context 里跑
        ctx = contextvars.copy_context()
        def _run():
            try:
                return ctx.run(fn)
            finally:
                with self._running_lock:
                    self._running.discard(session_id)
        pool = self._sequential_pool if serial else self._parallel_pool
        return pool.submit(_run)
```

教学点（每个都是 Hermes 踩过坑的教训）：
- `serial=True` 对应 Hermes 的 workdir job——**凡是会动进程全局状态的任务必须串行**
- running set 对应 `_running_job_ids`——同一任务不重叠执行（Hermes #79244 的坑：job 卡 running）
- `copy_context()` 对应 scheduler.py:4025——**任务里 set 的 contextvar 不会泄漏到别的任务**

### 4.3 存储：维持现状（每会话独立文件）

不引入 SQLite。理由（讨论结论）：
- 现有 JSON 文件已经是**文件级隔离**：不同会话写不同文件，零竞争
- 引入 SQLite 反而引入单写者问题（WAL、事务、重试）——为了解决一个不存在的问题
- 若未来需要跨会话搜索/统计，再迁移 SQLite 不迟（存储层接口留好即可）

---

## 5. 隔离保证矩阵（对照目标）

| 维度 | 机制 | 是否锁 |
|------|------|--------|
| 内存 | 每任务独立五模块实例（AgentSession 持有） | 无锁（结构性隔离） |
| 上下文 | copy_context + contextvar | 无锁（快照隔离） |
| 存储 | 每会话独立文件 | 无锁（文件级隔离） |
| 注册表 | dict + 单锁（仅保护增删查改） | 一把锁 |
| 失败 | 线程内 try/except，状态记入 AgentSession.status | — |
| 重叠执行 | running set + lock | 一把锁 |

**不隔离的（有意共享）**：配置、tools.py 内置工具函数（只读）——共享只读没问题，教学点：区分「只读共享」与「可变共享」。

---

## 6. 待讨论的决策点

1. ~~SQLite 单写线程 vs 多线程 + BEGIN IMMEDIATE~~ → **已取消**：维持每会话独立文件（§4.3）
2. **同会话新消息策略**：跳过（丢任务）还是排队？（Hermes 是 queue）
3. **任务状态机**：是否需要 idle→running→done/failed 三态 + 进度查询？还是只做 done/failed？
4. **AgentSession 是否继承现有 Session 类**：现有 Session 管 messages + JSON 文件；AgentSession 叠加五模块实例——是继承还是组合？
5. **失败隔离的粒度**：任务级 try/except 足够，还是需要 per-turn 重试（LLMClient 已有重试）？

---

## 7. 范围控制（本版明确不做）

- 不做多进程（multiprocessing）：教学级用不到，且引入序列化复杂度
- 不做 asyncio 改造：保持同步代码 + 线程池（对齐 V2 现有骨架的可读性）
- 不做跨任务通信（消息传递/共享队列给任务间协作）：先做隔离，再做协作
- 不引入第三方依赖：标准库足够

---

## 8. 与 V2.0 的关系

- **不动** conversation_loop.py 的核心骨架（30 行循环）
- **不动** 五模块现有接口（ConversationLoop 构造参数可能需要 session_id，最小侵入）
- **延续** session_manager.py（升级 Session → AgentSession，SessionManager → 注册表）
- **新增** task_scheduler.py（唯一新模块）
- 教学顺序：先讲「实例隔离」（为什么五模块天然支持多实例）→ 再讲「调度与去重」→ 最后讲「文件级存储隔离」

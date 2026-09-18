# MinimalAgentV2

从 **Hermes**（15 万行 Python 生产级 Agent）核心执行循环中提取的 Agent 框架：
**30 行核心骨架，五模块架构**，并实现 Plan Mode 硬约束、AgentIgnore 权限系统与技能插口。

Agent 的本质是 `LLM + Tools + Loop`。Hermes 的核心执行函数 `run_conversation`
有 5194 行，其中驱动 agent 工作的主循环只有 30 行：**问模型 → 有工具请求则执行并回填
→ 无工具请求则返回**。其余 4300 多行，是让它在真实世界不崩的防御。

本项目把这条主链完整提取出来，按职责拆成五个模块，防御逻辑全部下沉到模块内部，
让骨架保持可读；再在这个骨架上长出三层生产级机制：Plan Mode 硬约束、
AgentIgnore 权限控制、外部技能插口。

## 核心特性

### 1. 五模块拆分，骨架 30 行

核心循环只回答「下一步做什么」，五个模块各回答一个问题：

| 模块 | 回答的问题 |
|------|-----------|
| `LoopController` | 还继续吗（轮数 / 预算 / 中断 / grace） |
| `LLMClient` | 模型说什么（重试 / 退避 / 错误分类） |
| `ToolRunner` | 工具结果是什么（查找 / 解析 / 守卫 / 回填） |
| `MessageStore` | 消息放哪、太长怎么办（增删改查 / 压缩） |
| `TurnContext` | 回合开始前准备什么（系统提示词 / 清洗 / 凭证预检） |

每个模块都能在 Hermes 源码中找到对应的实现，对照表见 [CORE.md](CORE.md)。
模块划分不是凭空设计，是逆向提取的产物。

### 2. Plan Mode：规划 → 审批 → 执行 的硬闭环

`/plan` 进入规划模式：模型只读调研，用 `write_plan` 提交计划，状态变为「待审批」。
审批是**框架状态而非提示词**——模型未获 `/approve` 批准前无法退出规划模式
（`exit_plan_mode` 被守卫直接拒绝）；`/revise <反馈>` 把计划打回重写，`/cancel` 取消。
软约束（提示词）与硬约束（代码守卫）的对比，是理解「谁在强制、靠什么强制」的
最直接演示，配套对照 demo 见 [`hard-vs-soft-mode/`](hard-vs-soft-mode/)。

### 3. AgentIgnore：工具的文件系统权限控制

类似 `.gitignore` 的声明文件，每行 `绝对路径::权限码` 控制该路径允许哪些操作
（R / W / X 子集）。匹配采用前缀 + 权限交集：**父目录禁止的权限，子目录加不回来**。
读、写、执行三类工具统一过校验，拒绝时错误回填给模型——不崩溃、模型可见、可纠正。

### 4. 技能插口：宿主与技能包解耦

技能内容完全外置，独立的技能包（Superpowers 式）通过 `--skills-dir` 挂载。
会话开始自动注入技能索引与总开关，`load_skill` 按需加载技能全文。V2 插件子系统
（`plugin_manager / plugin_manifest / plugin_tools / plugin_hooks`）负责插件的安装卸载、
元信息加载、工具发现和 session-start hook 执行。不挂任何技能包时行为与原生一致。

### 5. 交互模式与会话管理

两种入口：单轮 `python3 cli.py "问题"`，或 `python3 cli.py -i` 进入 REPL
交互模式。REPL 提供完整的 slash 命令：

```
/new <名字>    新建会话        /plan   进入规划模式（只读调研 + 只能写计划文件）
/switch <名字> 切换会话        /run    退出规划模式，开始执行
/list          列出全部会话    /approve 批准当前计划（plan 模式）
/delete <名字> 删除会话        /revise <反馈> 按反馈修改计划
/exit /quit    退出           /cancel 取消计划并退出 plan 模式
```

会话管理采用**延迟落盘**：新会话聊了第一条真实消息才写盘，没聊过就走不产生任何文件；
每个会话独立 JSON 文件，会话之间零共享、零锁——多任务并发的隔离哲学是
「给每个人一个房子」。

## 快速开始

### 一键安装（推荐）

```bash
sh -c "$(curl -fsSL https://raw.githubusercontent.com/notfresh/mini-hermes-v2/main/install.sh)"
```

或克隆后本地安装：

```bash
git clone https://github.com/notfresh/mini-hermes-v2.git
cd mini-hermes-v2
./install-local.sh          # 写入 ~/.local/bin/mini-hermes
```

### 前置准备

```bash
export PATH="$HOME/.local/bin:$PATH"   # 未加到 shell 配置时需要
export DEEPSEEK_API_KEY=sk-xxx        # OpenAI 兼容接口
```

### 运行

```bash
mini-hermes --list-tools                                   # 列内置工具
mini-hermes "现在几点？"                                   # 单轮提问
mini-hermes "计算 (123+456)*2，然后读取 /etc/hostname"     # 触发工具调用
mini-hermes -v "列出当前目录"                               # 看每一轮的 token 与消息

# 交互模式（REPL：多会话 + /plan /run 等 slash 命令）
mini-hermes -i
```

### 项目内调试

```bash
cd minimal-agent-v2
source .venv/bin/activate               # 进入虚拟环境
export DEEPSEEK_API_KEY=sk-xxx

python3 cli.py "你好"                    # 直接跑，无需安装
python3 cli.py -v "..."                 # verbose 调试模式
python3 cli.py -i                       # REPL 交互模式
```

## 项目结构

```
minimal-agent-v2/
├── install.sh             # curl 一键安装脚本
├── install-local.sh       # 本地已有项目时安装 mini-hermes 命令
├── conversation_loop.py   # 核心循环骨架（30 行）
├── loop_controller.py     # 轮数 / 预算 / 中断控制
├── llm_client.py          # 重试 / 退避 / 错误分类
├── tool_runner.py         # 工具查找 / 解析 / 守卫 / 回填
├── tools.py               # @tool 注册中心 + 内置工具
├── message_store.py       # 消息增删改查 / 压缩
├── turn_context.py        # 回合准备：系统提示词 / 凭证预检
├── session_manager.py     # REPL 会话生命周期与持久化
├── plan_mode.py           # Plan Mode 状态机 + 守卫
├── agent_ignore.py        # AgentIgnore 路径权限校验
├── skill_registry.py      # 外部技能包扫描 / 注入
├── cli.py                 # 入口：单轮 / REPL / 调试
├── plugin_manager.py      # V2 插件管理（install/remove/list）
├── plugin_manifest.py     # V2 插件 manifest 加载器
├── plugin_tools.py        # V2 插件 tools 加载器
├── plugin_hooks.py        # V2 插件 hook 执行器
├── config.py              # 配置文件加载
└── hard-vs-soft-mode/     # 软 / 硬约束对照 demo
```

## 边界

本项目定位是教学与研究级实现：模型、网络、key 都正常时，它能完整展示 agent
的工作原理与上述机制。生产环境需要的凭证轮换、provider fallback、流式输出、
并发执行、LLM 摘要压缩等防御层，被**有意省略**——每一层都是设计上的取舍，
不是疏漏，逐项明细见 [v2.WHAT-WAS-DISCARDED.md](v2.WHAT-WAS-DISCARDED.md)。

## 档案导航

- **[CORE.md](CORE.md)** — 核心执行模型、五模块 ↔ Hermes 源码对照、蒸馏方法论（如何从 5194 行剥出 30 行）
- **[v2.WHAT-WAS-DISCARDED.md](v2.WHAT-WAS-DISCARDED.md)** — 逐项丢弃清单：砍掉的 85% 是什么、为什么
- **[docs/](docs/)** — 设计决策档案（Plan Mode 三版递进、AgentIgnore、多任务并发路线图等）

## 传承

- **V1**（`minimal-agent/`）：单文件实现，`agent_loop()` 一个函数装下核心循环 + 工具 + CLI
- **V2**（本仓库）：五模块工程化，并在骨架上实现 Plan Mode / AgentIgnore / 技能插口 / 会话管理
- **Hermes**：本项目的一切设计均有源码出处——它是 Hermes 核心思维的最小完整继承

## 路线图

每个勾选 = 亲手重建一层 Hermes 的真实防御（详见 [CORE.md](CORE.md) §5）：

- [ ] 流式输出
- [ ] 并发工具执行
- [ ] 凭证自动轮换
- [ ] 上下文 LLM 摘要压缩
- [ ] 记忆读写
- [ ] 子代理分发

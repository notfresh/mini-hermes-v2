# MinimalAgent 扩展协议设计（草案 v0.1）

> 目标：给 MinimalAgent（迷你 Hermes）设计一套**对外扩展协议**——
> 让外部开发者知道"为这个 agent 做扩展要遵循什么标准"，
> 像应用商店协议一样可分发、可发现、可安全加载。
> 设计参照：Hermes（优先）、Kimi Code、Claude Code、Superpowers 跨 harness 技能包。

**状态：草案，待决策点见文末。本文档只做设计，不含实现。**

---

## 1. 为什么需要协议

MinimalAgent 目前的能力扩展方式（现状）：

| 现状 | 问题 |
|---|---|
| `--skills-dir` 挂外部技能目录 | 只有 Skill 一种扩展，无工具/服务扩展 |
| `@tool` 装饰器（tools.py 内） | 只有"内置工具"，外部无法注册自己的工具 |
| `load_skill` 工具 | 技能加载，但无元数据规范/发现机制 |

要让 MinimalAgent 成为"可生长的 agent"（对应 Hermes 的
**"core is a narrow waist; capability lives at the edges"**），
需要一套协议回答四个问题：

1. **扩展长什么样？**（目录结构 + manifest）
2. **扩展怎么声明自己？**（注册协议）
3. **宿主怎么发现和加载？**（加载协议）
4. **怎么分发/安装？**（应用市场形态）

## 2. 四层扩展模型

扩展不是并列的，是四层（由底到顶）：

```
Plugin（打包单元）← 应用市场的"应用"，一个 plugin 可包含以下所有
 ├─ Tool    = 函数（模型可执行的动作：read/write/bash）——最底层原语
 ├─ Skill   = 方法论（教模型怎么思考的提示词，可调用 Tool）
 ├─ MCP     = 工具的网络协议（外部服务按标准暴露工具，跨应用通用）
 └─ Command = 用户触发的快捷指令（slash 命令）
```

层级关系：
- **Tool 是 Skill 的执行基础**：Skill 说"读文件"，靠 read 工具实现
- **MCP 是 Tool 的远程形态**：同一个 registry，MCP 工具注册进来后
  对模型无差别（都是 schema + handler）
- **Plugin 是分发单元**：把一组 Tool/Skill/MCP/Command 打包成
  可下载、可安装、可卸载的目录

## 3. 各 harness 协议调研（对照表）

| 维度 | Claude Code | Kimi Code | Hermes（重点参考） |
|---|---|---|---|
| Skill 规范 | agentskills.io：SKILL.md + frontmatter，渐进式披露 | SkillDefinition：name/desc/content/metadata/source | SKILL.md + frontmatter + `<available_skills>` 索引 |
| 工具注册 | 内置为主（插件可扩展） | tools/store.ts + builtin/policies | `registry.register(name, toolset, schema, handler, check_fn, requires_env)` |
| 插件声明 | plugin.json + marketplace.json（应用市场） | plugin.json 一体声明：skills/sessionStart/mcpServers/hooks/commands | plugins/ 目录 + 注册表 + 配置门控 |
| MCP | 业界标准（JSON-RPC stdio/SSE） | plugin.json 里声明 mcpServers | mcp_tool.py 动态注册，`mcp-` toolset 前缀防冲突 |
| 会话注入 | hooks（SessionStart 事件） | `sessionStart: {skill: "..."}` 声明式 | 技能索引注入（prompt_builder）+ skill_view 工具 |
| 冲突防护 | —（约定隔离） | — | **shadow 拒绝 + override opt-in + 插件权限策略** |
| 特色 | 约定优于配置 + 市场 | 一个 manifest 声明所有 | **统一注册表 + toolset 命名空间 + check_fn 服务门控** |

### 借鉴点提炼

1. **Hermes 的 register() 是完整协议**：外部注册工具 = 提供
   `name / toolset / schema / handler / check_fn / requires_env`。
   toolset 命名空间隔离来源，check_fn 做条件门控，override 做权限审计。
2. **Kimi 的 manifest 一体声明**：一个 plugin.json 声明该扩展的
   所有类型（skills + sessionStart + mcpServers + hooks + commands），
   宿主一次解析、统一注册。
3. **Claude Code 的市场形态**：marketplace.json 是分发协议，
   plugin.json 是声明协议，二者分离。
4. **Superpowers 的 invariants**：技能内容 harness 无关、工具映射
   per-harness、bootstrap 是"总开关"——扩展内容与宿主机制解耦。

## 4. MinimalAgent 协议设计

### 4.1 目录约定（扩展长什么样）

```
extensions/                         # 宿主扫描根目录（可配置）
└── my-extension/                   # 一个扩展 = 一个目录
    ├── extension.json              # ★ manifest（声明一切）
    ├── skills/                     # Skill 文件（SKILL.md 规范）
    │   └── my-skill/SKILL.md
    ├── tools/                      # 工具代码（Python 模块）
    │   └── my_tools.py
    └── README.md                   # 人类可读文档（可选）
```

### 4.2 manifest 规范（extension.json）

```json
{
  "name": "my-extension",
  "version": "1.0.0",
  "description": "一句话描述",
  "author": {"name": "zx", "email": "zx@example.com"},
  "license": "MIT",
  "skills": "./skills/",
  "sessionStart": {"skill": "using-superpowers"},
  "tools": "./tools/",
  "commands": [
    {"name": "mycmd", "description": "...", "handler": "my_tools:my_command"}
  ],
  "mcpServers": {
    "my-server": {"command": "npx", "args": ["-y", "@my/mcp-server"], "env": {}}
  }
}
```

字段说明：
- `skills`：技能目录相对路径（SKILL.md 规范见 4.4）
- `sessionStart`：可选。声明会话开始时注入哪个技能（bootstrap 约定）
- `tools`：工具代码目录，`@tool` 装饰器注册（与内置工具同机制）
- `commands`：slash 命令（用户触发，`模块:函数` 定位）
- `mcpServers`：MCP 服务器配置（stdio 启动命令）

### 4.3 注册表设计（ToolRegistry，学 Hermes）

```python
# 协议核心：外部扩展注册一个工具要提供什么
registry.register(
    name=str,              # 工具名（模型调用名，自动加扩展名前缀防冲突）
    toolset=str,           # 来源命名空间："builtin" / "ext:<name>" / "mcp:<server>"
    schema=dict,           # OpenAI 兼容 JSON Schema（给模型看）
    handler=callable,      # 执行函数
    check_fn=callable|None,    # 服务门控：条件满足才暴露
    requires_env=list|None,    # 声明的环境变量依赖
    override=False,            # 覆盖已有工具需显式 opt-in
)
```

三条规则（对应 Hermes 的防护）：
1. **命名空间隔离**：扩展工具注册为 `ext:my-extension` toolset，
   与内置工具天然隔离；同名冲突默认拒绝注册
2. **override 需显式声明**：扩展想替换内置工具（如换 bash 实现），
   manifest 里声明 + 用户配置允许，否则拒绝
3. **check_fn 门控**：工具按条件暴露（如 `requires_env` 未满足则
   不进 schema，模型根本看不到）

### 4.4 Skill 规范（沿用已验证的 SKILL.md）

```
skills/<name>/SKILL.md
---
name: my-skill                      # 必填，唯一
description: Use when doing X...    # 必填，模型决策依据（≤1024字符）
---
# 正文：行为塑形提示词
<HARD-GATE> ... </HARD-GATE>
## Checklist
1. ...
## Red Flags
| 想法 | 现实 |
```

- 宿主注入 `<available_skills>` 索引（name + description），全文按需加载
- 技能包自带 `using-superpowers` 时自动注入总开关（bootstrap 约定，
  已在 skills-framework 分支实现）

### 4.5 加载与发现

```
启动时：
  1. 扫描 extensions/ 目录（配置指定，可多个）
  2. 解析每个 extension.json（校验必填字段）
  3. 注册：tools 目录 @tool 扫描 → registry.register
           skills 目录 → SkillRegistry 索引
           mcpServers → 启动 MCP 客户端 → 工具动态注册
  4. 注入：sessionStart 声明的技能 → bootstrap
运行时：
  5. 模型看到工具 schema + <available_skills> 索引
  6. 按需 load_skill / 调用工具
```

### 4.6 分发形态（应用市场，第二期）

- **目录分发**（一期）：`--extensions-dir <path>` 挂载本地扩展
- **GitHub 分发**（二期）：`extension install <github-repo>`——
  克隆到 extensions/，校验 manifest 完整性（对应 Kimi 的
  plugin-source: github；Claude Code 的 marketplace.json）

## 5. 与现有代码的关系

| 现有（skills-framework 分支） | 协议中的位置 |
|---|---|
| `--skills-dir` + SkillRegistry | 4.4 Skill 规范（协议子集） |
| `load_skill` 工具 | 技能加载（协议已有） |
| bootstrap 约定（using-superpowers 自动注入） | 4.2 `sessionStart` 字段的隐式形态 |
| `@tool` 装饰器 + ToolRunner | 4.3 注册表（升级为带命名空间的 ToolRegistry） |

即：**协议 = 现有技能插口的泛化**——Skill 插口推广到
Tool/MCP/Command/Plugin 全类型，并补上命名空间与冲突防护。

## 6. 待决策点（讨论用）

1. **第一版范围**：
   - A. 全四层（Tool + Skill + MCP + Plugin）
   - B. 只 Tool + Skill（MCP 太重量级）
   - C. 只 Plugin + Skill（聚焦市场形态）
   - D. 只写文档不实现
2. **manifest 格式**：JSON（Kimi/Claude 风格）vs TOML（Python 原生）vs YAML
3. **扩展目录位置**：项目内 `extensions/` vs 用户目录 `~/.minimal-agent/extensions/`
4. **MCP 是否接入**：若做，用哪个客户端库（零依赖手写 stdio 客户端 vs mcp 库）
5. **命令前缀**：扩展工具是否强制加 `ext:<name>_` 前缀（防冲突 vs 可读性）

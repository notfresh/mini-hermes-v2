# MinimalAgent V2 — AgentIgnore 路径权限设计方案

日期：2026-08-17
状态：v0.1 已实现（分支 agent-ignore，基于 plan-mode-v2）
范围：ToolRunner 执行链上加路径级权限校验（R 读 / W 写 / X 执行），配套 AgentIgnore 配置文件
用户验收时间：2026-08-17 上午

---

## 0. 需求（用户原话提炼）

- 做一个类似 `.gitignore` 的配置文件，叫 **AgentIgnore**，控制 agent 工具对文件系统的访问
- 某些文件/目录**禁止读或禁止写**——借鉴 Linux 目录权限 **RWX** 三分类：R=read、W=write、X=execute
- 匹配**绝对路径**；tools 里每个工具按 R/W/X 归类，**每次工具调用前校验**，路径命中规则即禁用
- 目录禁止读 = 子目录、文件全禁；子目录想"开小窗"允许读——**第一版不做**（做减法）
- 语法一行一条：`绝对路径::权限码`（如 `/home/user/private::WX` 表示禁止读）

## 1. 设计原则

1. **对齐 Plan Mode V2 守卫**：ToolRunner 已有 `self.guard` 执行前检查点（`execute()` 内、工具执行前，违规返回错误 Observation 不崩溃）——AgentIgnore 校验做**第二个守卫**，同构复用，不另起炉灶
2. **骨架零改动**：conversation_loop.py 不动——校验点全在 ToolRunner.execute 一处，所有工具调用都经过它
3. **默认放行，向后兼容**：AgentIgnore 文件不存在 / 规则未命中 = 完全原行为；只有显式写规则才收紧
4. **拒绝信息回填给 LLM**（错误 Observation，模型能看到原因继续推理）——与现有防御风格一致
5. **教学可见**：模块头注明 Hermes/Kimi 对应关系（V2 惯例）

## 2. 语法设计

```
# 注释行（# 开头）
空行忽略

/绝对/路径::权限码
```

- **路径**：必须是绝对路径（非绝对路径的行忽略并警告）；可指向文件或目录，目录规则作用于整棵子树
- **权限码**：`R`/`W`/`X` 任意组合，**= 允许的权限，缺哪个字母就禁止哪个操作**（Linux 语义）
- 示例：

| 规则 | 含义 |
|------|------|
| `/home/user/.ssh::` | 完全禁止（不可读、写、执行） |
| `/home/user/private::R` | 只允许读（禁止写、禁止执行） |
| `/tmp/sandbox::WX` | 允许写和执行，禁止读 |
| `/data/backup::RW` | 允许读写，禁止执行 |

## 3. 匹配与合并规则（做减法）

- **前缀匹配**：规则路径是目标路径的前缀即命中（目录规则覆盖子树）；文件规则精确匹配
- **合并 = 权限交集**：目标路径最终权限 = 所有命中规则权限码的**交集**；无命中 = 默认 `RWX` 全允许
- 因此**父目录禁止的权限，子目录规则加不回来**——天然实现"目录禁止读，子目录允许读也不行"，且不需要"最先匹配优先"的排序逻辑（交集本身就是最严格的）
- **路径归一化**：规则与目标路径都经 `normpath(abspath())`——相对路径（`../`、`./`）解析成绝对路径再匹配，防绕过
- 第一版**不做"开小窗"**（显式放行覆盖父级规则），后续版本再做

## 4. 工具 ↔ 权限映射（V2 内置 9 工具）

| 工具 | 权限 | 校验的路径参数 | 说明 |
|------|------|----------------|------|
| read | R | path | 读文件 |
| ls | R | path | 列目录 |
| grep | R | path | 搜文件内容 |
| find | R | path | 按名找文件 |
| head | R | path | 前 N 行（read 包装） |
| write | W | path | 写文件 |
| bash | X | （无） | 从 command 字符串提取绝对路径逐个校验 X |
| load_skill | — | — | 无文件路径参数，不校验 |
| get_time / calculator | — | — | 无文件操作，不校验 |

**bash 的处理**（第一版）：bash 没有结构化路径参数，从 `command` 字符串正则提取绝对路径（`(?:^|\s)(/[^\s'"]+)`），按 **X（执行）** 校验。局限：`bash "cat /secret/x"` 这类内嵌读写无法按 R/W 精确拦截——bash 本质是任意 shell，彻底拦截需要 shell 审计层，明确留作后续（见 §8）。但 `::` 全禁路径能被 X 校验挡住（全禁路径无 X）。

## 5. 校验点与执行流

```
LLM 工具调用
  → ToolRunner.execute(tool_call)
      → 参数解析 fn_name / fn_args
      → [检查点 1] plan_guard（Plan Mode V2：规划期只允许写计划文件）
      → [检查点 2] agent_ignore.check_tool(fn_name, fn_args)   ← 新增
          命中规则且权限不足 → 返回 {"role":"tool", content:"错误：AgentIgnore 权限校验失败: ..."}
      → 真正执行工具函数
```

注入点（cli.py，与 plan_guard 注入同构）：

```python
tools_runner = ToolRunner(verbose=args.verbose)
tools_runner.agent_ignore = AgentIgnore.load_default()   # ~/.minimal-agent-v2/AgentIgnore，不存在 → None
```

## 6. 安全考量（用户强调"一定要安全"）

1. **校验先于执行**：检查点在 execute() 内、工具函数调用之前，拒绝时工具完全不执行
2. **防 `..` 绕过**：所有路径 `normpath(abspath())` 归一化，`/a/../b` 与 `/b` 等价匹配
3. **防相对路径绕过**：工具传相对路径同样转绝对路径匹配（规则必须是绝对路径，从语法层杜绝歧义）
4. **AgentIgnore 文件本身可被规则保护**：如 `~/.minimal-agent-v2/AgentIgnore::` 禁止工具改动它（自保护）
5. **已知局限（如实记录，后续版本处理）**：
   - **符号链接**：用 normpath 不跟随链接，`/link` → `/real` 的链接可绕过 `/real` 的规则（后续用 realpath 解析）
   - **bash 内嵌读写**：只按 X 拦截，`cat`/`rm` 的 R/W 语义无法判断（后续做命令解析或 shell 审计）
   - **`~` 开头路径**：不展开，需写绝对路径（文档说明）

## 7. 改动文件清单

| 文件 | 改动 | 规模 |
|------|------|------|
| `agent_ignore.py`（新增） | AgentIgnore 类：解析 + 匹配交集 + check_path/check_tool + 工具映射表 | ~150 行 |
| `tool_runner.py` | `__init__` 加 `self.agent_ignore = None`；execute() 加检查点 | +6 行 |
| `cli.py` | 交互模式 + 消息模式各注入一次 `AgentIgnore.load_default()` | +4 行 |
| 测试脚本（/tmp） | 规则解析 / 前缀交集 / 工具拦截 / bash 提取 | 验证用 |

## 8. 后续版本（YAGNI 待办，不做不写）

- V2-1：开小窗例外（子目录显式放行覆盖父级）
- V2-2：符号链接 realpath 解析
- V2-3：bash 命令细粒度解析（区分命令的 R/W 语义）
- V2-4：`--agent-ignore <path>` 参数指定配置文件位置

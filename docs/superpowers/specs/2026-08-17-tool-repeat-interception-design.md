# Tool Repeat Interception — 工具重复调用拦截

> Spec for: minimal-agent-v2
> Status: approved (pending user review)
> Date: 2026-08-17
> Inspired by: Kimi CLI `KimiToolset.handle` 重复检测 (Python legacy `src/kimi_cli/soul/toolset.py`)

## 目标

当 LLM 反复以**相同工具名 + 相同参数**调用同一个工具时,自动:
1. 在工具返回结果上追加 `<system-reminder>` 软提醒,促使 LLM 换思路
2. 当重复次数达到上限时,强制结束回合(`exit_reason="tool_call_repeat"`),不再让 LLM 继续浪费 token

镜像 Kimi CLI 的 `KimiToolset` 重复检测模式,但简化为两档阈值(软提醒 + 强制停止),避免中间档位带来的复杂度。

## 设计范围

- **新增**:`ToolRunner` 内部的重复检测状态机、`@tool` 装饰器的 `skip_repeat_check` 选项、`ConversationLoop` 的 `force_stop` 接入
- **修改**:`tool_runner.py` / `conversation_loop.py` / `cli.py`
- **不修改**:`loop_controller.py`(沿用现有 max_turns 机制)、`message_store.py`、`llm_client.py`、`tools.py`(内置工具不强制 opt-out)

## 数据模型

### 1. Canonical Arguments(规范化参数)

工具调用的"身份 key" = `(tool_name, canonical_args_str)`。

**canonical_args_str 算法**:
1. 如果 `tool_call.function.arguments` 为空字符串 → 使用 `""`
2. 否则尝试 `json.loads(arguments_str)`
   - 解析失败 → fallback 为**原始字符串**(避免误判 streak 重置,保持最大兼容性)
3. 对解析结果递归规范化:
   - `dict` → 按 key 排序后递归处理子项
   - `list` → 保持顺序递归处理子项(list 顺序敏感,不像 dict)
   - 其它类型 → 原值
4. 用 `json.dumps(..., ensure_ascii=False, separators=(",", ":"))` 序列化

实现位置:`tool_runner.py` 私有函数 `_canonicalize_args(args_str: str) -> str`。

**示例**:
- `{"a": 1, "b": 2}` 和 `{"b": 2, "a": 1}` 规范化后**相等**(dict 顶层 key 排序)
- `[{"x": 1}, {"x": 2}]` 和 `[{"x": 2}, {"x": 1}]` 规范化后**不相等**(list 顺序敏感);但 list 内部的 dict 仍按 key 排序
- `"hello"` 和 `"hello "`(带尾空格)规范化后**不相等**(字符串本身是 atomic 的,不做归一化)
- `"not json"` 解析失败 → fallback 到原文,后续比较字面量

### 2. ToolRunner 状态

新增私有属性:

```python
class ToolRunner:
    def __init__(self, verbose=False):
        ...
        self.soft_repeat_threshold = 3   # >= 这个 streak 触发软提醒
        self.stop_repeat_threshold = 8   # >= 这个 streak 触发强制停止
        # 内部状态
        self._prev_step_keys: list[tuple[str, str]] = []  # 上一步出现过的 key
        self._streaks: dict[tuple[str, str], int] = {}   # 每个 key 的当前 streak
        self._current_step_keys: list[tuple[str, str]] = []
        self._force_stop: bool = False
```

### 3. @tool 装饰器 opt-out

```python
def tool(name="", description="", skip_repeat_check=False):
    def decorator(func):
        ...
        _TOOL_REGISTRY[tool_name] = {
            "fn": func,
            "schema": schema,
            "skip_repeat_check": skip_repeat_check,
        }
```

`skip_repeat_check=True` 的工具走**短路逻辑**:不参与 streak 计数,不接收 reminder,**也不触发 streak 清空**(本步出现 opt-out 工具不会让其他 key 的 streak 清空)。force_stop 是 step 级属性,一旦设置后本 step 后续所有 tool_call 都跳过 streak 检查(即便非 opt-out)。

## 核心算法

### 单步执行流程(`execute_all` 内部)

`ToolRunner.execute_all` 在执行每个 tool_call 前**先调用**内部 `_begin_step()`(幂等,只在第一次调用时生效),然后对每个 call 走以下流程:

```
def execute(self, tool_call):
    name = tool_call["function"]["name"]
    raw_args = tool_call["function"].get("arguments", "") or "{}"
    key = (name, _canonicalize_args(raw_args))

    entry = _TOOL_REGISTRY.get(name)
    if entry is None:
        # 工具不存在 → 跳过 streak(返回的 content 已被规范化)
        return _error_result(...)

    # opt-out 工具:不计入 streak,但工具照跑
    if entry.get("skip_repeat_check"):
        return _run_and_return(...)

    # streak 计算
    if key in _streaks:
        streak = _streaks[key] + 1
    else:
        # 首次出现 → 清空所有 streak(换 key 了)
        _streaks.clear()
        streak = 1
    _streaks[key] = streak
    _current_step_keys.append(key)

    # 执行工具
    result = _run_tool(entry, ...)

    # 追加 reminder(如果达到阈值)
    if streak >= stop_repeat_threshold:
        result["content"] += _STOP_REMINDER.format(streak=streak)
        self._force_stop = True
    elif streak >= soft_repeat_threshold:
        result["content"] += _SOFT_REMINDER.format(streak=streak)

    return result
```

### `begin_step()`(循环骨架在每轮开头调一次)

```python
def begin_step(self):
    """由 ConversationLoop 在每轮调用 execute_all 之前调用一次。"""
    self._current_step_keys = []
    # 如果上一步没有工具调用,重置所有 streak(新一轮开始)
    if not self._prev_step_keys:
        self._streaks.clear()
    self._force_stop = False  # 每步重新评估
```

> 注:每步开始时**不**无条件清空 `_streaks`,而是看 `_prev_step_keys`——如果上一步没有 tool_calls,说明模型换了非工具路径,清空 streak 是合理的;如果上一步有 tool_calls,则继续累计。

### `end_step()`(循环骨架在每轮收尾调一次)

```python
def end_step(self):
    """由 ConversationLoop 在每轮 execute_all 之后调用一次。"""
    self._prev_step_keys = list(self._current_step_keys)
```

### `force_stop` 属性

```python
@property
def force_stop(self) -> bool:
    return self._force_stop
```

## Reminder 文案

### 软提醒(soft_repeat_threshold ≤ streak < stop_repeat_threshold)

```
<system-reminder>
你正在重复调用同一个工具 '{name}' (已连续 {streak} 次),参数完全相同。
请仔细回顾之前的工具返回内容,考虑是否需要换一个完全不同的思路或不同的参数。
</system-reminder>
```

### 强制停止提醒(streak ≥ stop_repeat_threshold)

```
<system-reminder>
⚠️ 你已经连续 {streak} 次以完全相同的参数调用工具 '{name}',陷入死循环。
这是最后一次机会:请立刻停止所有工具调用,用纯文本回复用户,总结你目前已经掌握的信息。
</system-reminder>
```

附在 `result["content"]` 的**末尾**,以换行分隔。LLM 仍然看到原始工具结果,只是末尾多了提醒。

## ConversationLoop 集成

### `__init__` 新增参数

```python
def __init__(
    self,
    llm: LLMClient,
    tools: ToolRunner,
    controller: Optional[LoopController] = None,
    skills: Optional[SkillRegistry] = None,
    max_context_tokens: int = 8000,
    verbose: bool = False,
    *,
    soft_repeat_threshold: int = 3,    # 新增
    stop_repeat_threshold: int = 8,    # 新增
):
```

把这两个传给 ToolRunner:
```python
self.tools.soft_repeat_threshold = soft_repeat_threshold
self.tools.stop_repeat_threshold = stop_repeat_threshold
```

### run() 主循环的"工具调用"分支

在原有代码:
```python
if assistant.get("tool_calls"):
    messages.append_assistant_with_tool_calls(assistant)
    results = self.tools.execute_all(assistant["tool_calls"])
    for r in results:
        messages.append(r)
    self.stats["tool_calls"] += len(results)

    # 3. 超长压缩
    if messages.compress_if_needed(self.max_context_tokens):
        self.stats["compressions"] += 1
    continue
```

修改为:
```python
if assistant.get("tool_calls"):
    self.tools.begin_step()
    messages.append_assistant_with_tool_calls(assistant)
    results = self.tools.execute_all(assistant["tool_calls"])
    for r in results:
        messages.append(r)
    self.stats["tool_calls"] += len(results)
    self.tools.end_step()

    if self.tools.force_stop:
        return self._force_stop_result(messages)

    # 3. 超长压缩
    if messages.compress_if_needed(self.max_context_tokens):
        self.stats["compressions"] += 1
    continue
```

### 新增 `_force_stop_result`

```python
def _force_stop_result(self, messages: MessageStore) -> dict:
    return {
        "final_response": "(工具重复调用达到上限,已强制结束回合)",
        "messages": messages.snapshot(),
        "api_calls": self.stats["api_calls"],
        "tool_calls": self.stats["tool_calls"],
        "exit_reason": "tool_call_repeat",
        "error": "tool_call_repeat",
    }
```

## CLI 暴露

`cli.py` 的 argparse 增加两个 flag:

```python
parser.add_argument("--soft-repeat-threshold", type=int, default=3,
                    help="工具重复调用软提醒阈值 (0 = 禁用)")
parser.add_argument("--stop-repeat-threshold", type=int, default=8,
                    help="工具重复调用强制停止阈值 (0 = 禁用)")
```

传入到 `ConversationLoop(...)` 构造时作为命名参数。

**默认行为**:`soft=3, stop=8` —— 默认开启,无需任何 flag。

**关闭方法**:两个 flag 都传 0(此时 ToolRunner 不追加任何 reminder、不设置 force_stop,行为与改动前完全一致)。

## 错误处理

| 场景 | 行为 |
|------|------|
| 工具不存在 | `execute` 在 streak 计算之前返回 error result,**不**计入 streak |
| 参数 JSON 解析失败 | `_canonicalize_args` fallback 到原始字符串字面量比较 |
| 工具执行抛出异常 | 工具照常返回 error result(经 `except Exception` 捕获的 JSON 错误对象);streak 仍然递增(因为参数 key 相同) |
| `skip_repeat_check=True` 的工具 | 不参与 streak 计算,不接收 reminder |
| force_stop 已 True 后,该步剩余 tool_call | **照常执行工具调用**(我们不中断已开始的 step),但**跳过 streak 检查与 reminder 追加**(避免 step 内重复提示);本步结束后 ConversationLoop 因 force_stop 退出循环 |

## 测试策略

### 单元测试(新增 `test_tool_repeat.py`)

1. **`test_canonicalize_args_dict_order_insensitive`**: 验证 `{"a":1,"b":2}` ≡ `{"b":2,"a":1}`
2. **`test_canonicalize_args_list_order_sensitive`**: 验证 `[1,2]` ≠ `[2,1]`
3. **`test_canonicalize_args_invalid_json`**: 验证非法 JSON fallback 到原文
4. **`test_streak_increment_same_call`**: 连续 3 次同名同参调用,第 3 次 content 含 `<system-reminder>`
5. **`test_streak_reset_on_key_change`**: A B A 调用后,A 的 streak 重置为 1
6. **`test_force_stop_after_threshold`**: 连续 8 次同名同参,第 8 次触发 force_stop,后续 step 不再执行
7. **`test_skip_repeat_check_opt_out`**: opt-out 工具连续调用 10 次,force_stop 仍然 False
8. **`test_reminder_not_added_below_threshold`**: streak < soft_threshold 时无 reminder
9. **`test_force_stop_in_conversation_loop`**: 集成测试,ConversationLoop 返回 `exit_reason="tool_call_repeat"`

### 回归测试

- 现有所有手动测试场景(README 中的 `计算 (123+456)*2,然后读取 /etc/hostname`)不能因为新功能挂掉——验证 streak=1/2 时不附加 reminder,行为不变。

## 兼容性

- **向后兼容**: 默认行为变化对正常 LLM 无影响(LLM 在 step 1-2 不会触发任何 reminder)。回归测试需确认。
- **API 兼容**: `ConversationLoop.__init__` 新增两个 keyword-only 参数(放在 `*` 后面),现有调用者不受影响。
- **CLI 兼容**: 新增的两个 flag 都有默认值,不传则行为如规格所述。
- **统计兼容**: `stats["tool_calls"]` 计数方式不变(每次 execute 调用 +1)。

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| canonical_args 对超长参数(如读取大文件)计算成本高 | canonicalize 是 O(n) 算法,典型参数对象远小于文件内容;风险低 |
| LLM 看到 reminder 后反而陷入更糟的循环 | reminder 文案明确要求"立刻停止",且 force_stop 是硬约束 |
| opt-out 装饰器参数破坏现有 `@tool(...)` 调用 | skip_repeat_check 是 keyword-only 默认值 False,向后兼容 |
| 不同 LLM 对 `<system-reminder>` 标签敏感度不同 | 沿用 Kimi 的成熟文案格式 |
| 某些合理的"重试"模式被误判(如网络失败重试) | 工具内部自己处理重试,LLM 调用层看不到失败;LLM 视角的"重试"通常伴随参数变化(比如加 retry_count) |

## 不在本期范围

- 跨会话的重复检测(本期只在一次 `ConversationLoop.run()` 内)
- 同步骤重复调用的去重/合并(本期同步骤重复也计 streak,不优化)
- 三档或更多档的提醒阶梯(本期只两档)
- 工具失败 vs 成功的区分(本期只重复 key,不区分结果)
- 基于 LLM 行为的"语义相似度"检测(本期只做字面 canonical_args 比较)
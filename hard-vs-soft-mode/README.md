# Hard vs Soft Mode — 软约束 vs 硬约束

一个 Hello World 级 demo，对比"约束 LLM 行为的两种方式"到底差在哪。

- **软模式**（`soft_mode.py`）：规则写在 system prompt 文本里，靠模型自觉遵守
- **硬模式**（`hard_mode.py`）：规则编译成 guard 函数，工具执行前由框架代码强制检查

## 一句话

**软 = 提示词约定（守不守取决于模型）；硬 = 代码强制（谁来了都得守）。**

## 运行

```bash
python3 soft_mode.py
python3 hard_mode.py
```

零第三方依赖，纯 Python 标准库；用模拟模型（乖/叛逆）代替真实 LLM，
这样差异完全来自模式本身，可复现、不花钱。

## 场景

系统规则：**禁止写入 forbidden.txt**。用户请求：把 hello 写入 forbidden.txt。
两个模型分别尝试：乖模型（会读提示词）、叛逆模型（无视提示词）。

## 输出对照（2 模型 × 2 模式）

```
                软模式(prompt 文字)        硬模式(guard 代码)
乖模型(守规矩)   拒绝 ✓                   拒绝 ✓
叛逆模型(不守)   违规成功 ✗  ← 没人拦      被 DENIED 拦截 ✓ ← 代码拦
```

## 代码差异（就一行）

```python
# soft_mode.py —— 规则是文字，执行无检查
result = execute_tool(name, args)                    # guard=None

# hard_mode.py —— 规则是代码，执行前强制检查
result = execute_tool(name, args, guard=hard_guard)  # 违规 → DENIED
```

## 真实世界的对应

| 本项目      | 真实框架                                                     |
|-------------|--------------------------------------------------------------|
| soft_mode   | Hermes 的 plan skill / todo 工具（提示词引导，无强制）        |
| hard_mode   | Kimi Code 的 plan-mode-guard-deny（permission 策略 deny 拦截）|
| Decision    | LLM 的 tool_call 输出                                         |
| execute_tool | 工具执行器（Hermes: tool_executor.py）                       |

## 思考题

1. 软模式为什么拦不住叛逆模型？——因为规则只是文本，没有任何代码在工具执行前检查它。
2. 硬模式的代价是什么？——每次工具调用多一层检查；规则写死在代码里，改规则要改代码重发版。
3. 真实系统为什么两者都有？——软模式便宜灵活（改 prompt 就能改规则），硬模式可靠（关键安全边界必须代码兜底）。Kimi 的 plan mode 正是"软提示 + 硬守卫"组合：提示词告诉模型该干嘛，guard 保证它不能越界。

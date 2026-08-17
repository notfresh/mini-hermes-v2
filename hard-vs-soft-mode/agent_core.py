"""agent_core.py — 极简 Agent 骨架：决策 → 守卫检查 → 工具执行

软/硬两种模式的唯一区别就在 execute_tool 的 guard 参数：

    软模式: guard=None       → 规则只存在于 system prompt 文本里，执行零检查
    硬模式: guard=hard_guard → 规则编译成代码，每次工具调用先过守卫

Hermes 对应: tools/registry.py + agent/tool_executor.py
Kimi Code 对应: permission/policies/plan-mode-guard-deny.ts（deny 拦截）
"""

from dataclasses import dataclass

# 系统唯一"禁区"：任何模式下都不允许写入的文件
FORBIDDEN_FILE = "forbidden.txt"

def read_file(path: str) -> str:
    """只读工具：任何模式都放行。"""
    return f"<{path} 的内容：'hermes' 是希腊神话中的赫尔墨斯>"


def write_file(path: str, content: str) -> str:
    """写文件工具：软/硬模式的试金石。"""
    return f"已写入 {path}: {content}"


TOOLS = {"read_file": read_file, "write_file": write_file}


def execute_tool(name: str, args: dict, guard=None):
    """执行工具。guard 存在时先检查——这就是"硬"的落点。

    guard(name, args) 返回 None 表示放行；返回字符串表示拒绝原因。
    拒绝时工具不执行，模型收到一条 error 结果（跟 Kimi 的 deny 语义一致）。
    """
    if guard is not None:
        reason = guard(name, args)
        if reason:
            return {"error": f"DENIED: {reason}"}
    return TOOLS[name](**args)


@dataclass
class Decision:
    """模型的决策：要么调用工具，要么直接回复。"""

    kind: str  # "tool" | "reply"
    tool: str = ""  # tool 时的工具名
    args: dict = None  # tool 时的参数
    text: str = ""  # reply 时的回复内容


def run_agent(model, system_prompt: str, request: str, guard=None) -> str:
    """极简 Agent 循环：模型决策 →（守卫检查）→ 工具执行 → 模型总结。"""
    decision = model.reason(system_prompt, request)
    if decision.kind == "reply":
        return decision.text
    result = execute_tool(decision.tool, decision.args, guard=guard)
    return f"任务结束。工具结果：{result}"

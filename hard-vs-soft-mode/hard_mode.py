"""hard_mode.py — 硬模式：规则编译进 guard 函数，工具执行前强制检查

谁在强制？框架代码。
每次工具调用都先过 guard，违规直接返回 DENIED、工具不执行——
模型"想"违规也办不到，因为决定权在代码手里，不在模型手里。

真实对应: Kimi Code 的 plan-mode-guard-deny 权限策略
（plan mode 激活时 Write/Edit 非计划文件 → kind: 'deny'，工具被拦截）
"""

from agent_core import FORBIDDEN_FILE, run_agent
from models import ObedientModel, RecklessModel

# 规则写成了代码：guard 是工具执行前的强制检查关卡
def hard_guard(name: str, args: dict):
    if name == "write_file" and args.get("path") == FORBIDDEN_FILE:
        return f"禁止写入 {FORBIDDEN_FILE}"
    return None  # 放行


HARD_PROMPT = f"你是 Minimal Agent。系统规则：禁止写入 {FORBIDDEN_FILE}。"
REQUEST = f"把 'hello' 写入 {FORBIDDEN_FILE}"


def main() -> None:
    print("=" * 56)
    print("【硬模式】规则编译进 guard 函数，工具执行前强制检查")
    print("=" * 56)
    print(f"\n用户请求: {REQUEST}")
    print(f"系统规则: 禁止写入 {FORBIDDEN_FILE}（写进了 guard 代码，硬性关卡）\n")

    print("① 乖模型（会读提示词的模型）：")
    print(f"   -> {run_agent(ObedientModel(), HARD_PROMPT, REQUEST, guard=hard_guard)}")

    print("\n② 叛逆模型（无视提示词的模型）：")
    print(f"   -> {run_agent(RecklessModel(), HARD_PROMPT, REQUEST, guard=hard_guard)}")

if __name__ == "__main__":
    main()

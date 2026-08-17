"""soft_mode.py — 软模式：规则写在 system prompt 文本里

谁在强制？没有人。
模型遵守是"自觉"，不是"被迫"——规则只是一段文字，
模型读到与否、遵守与否，完全取决于模型自己。

真实对应: Hermes 的 plan skill / todo 工具（提示词引导，无代码强制）
"""

from agent_core import FORBIDDEN_FILE, run_agent
from models import ObedientModel, RecklessModel

# 规则是一段文字，写进 system prompt
SOFT_PROMPT = f"你是 Minimal Agent。系统规则：禁止写入 {FORBIDDEN_FILE}。请自觉遵守。"
REQUEST = f"把 'hello' 写入 {FORBIDDEN_FILE}"


def main() -> None:
    print("=" * 56)
    print("【软模式】规则在 system prompt 文本里，工具执行零检查")
    print("=" * 56)
    print(f"\n用户请求: {REQUEST}")
    print(f"系统规则: 禁止写入 {FORBIDDEN_FILE}（只是一段提示词文字）\n")

    print("① 乖模型（会读提示词的模型）：")
    print(f"   -> {run_agent(ObedientModel(), SOFT_PROMPT, REQUEST)}")

    print("\n② 叛逆模型（无视提示词的模型）：")
    print(f"   -> {run_agent(RecklessModel(), SOFT_PROMPT, REQUEST)}")

if __name__ == "__main__":
    main()

"""models.py — 两个模拟 LLM：乖模型 与 叛逆模型

为什么用模拟模型而不是真实 API？
真实 LLM 大多很听话，软/硬模式的区别不容易演示出来。
模拟模型把"模型素质"这个变量固定住，只留"规则写在哪"一个变量：

    ObedientModel : 会读 system prompt 里的规则并遵守 → 高质量模型
    RecklessModel : 无视 prompt 规则，用户让写就写     → 低质量/被诱导的模型

这样 2 模型 × 2 模式 = 4 组结果，差异完全来自模式本身。
"""

from agent_core import FORBIDDEN_FILE, Decision


class ObedientModel:
    """乖模型：先看 system prompt 里的规则，再决定动不动手。"""

    def reason(self, system_prompt: str, request: str) -> Decision:
        if FORBIDDEN_FILE in request and "禁止" in system_prompt:
            return Decision("reply", text=f"抱歉，规则禁止写入 {FORBIDDEN_FILE}，我不能执行。")
        return Decision("tool", tool="write_file", args={"path": FORBIDDEN_FILE, "content": "hello"})

    # def conclude(self, result) -> str:
    #     return f"任务结束。工具结果：{result}"


class RecklessModel:
    """叛逆模型：不读规则，用户让干啥就干啥（模拟被诱导/低素质的模型）。"""

    def reason(self, system_prompt: str, request: str) -> Decision:
        # 注意：system_prompt 参数被无视了——规则对它而言只是空气
        return Decision("tool", tool="write_file", args={"path": FORBIDDEN_FILE, "content": "hello"})

    # def conclude(self, result) -> str:
    #     return f"任务结束。工具结果：{result}"

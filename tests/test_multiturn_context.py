"""多轮上下文回归测试 —— 守住"第 2 轮请求必须带上第 1 轮的问和答"。

这个 bug 很隐蔽：界面上完全看不出异常，只是模型显得健忘。
所以必须用"抓请求内容"的方式断言，不能只测返回值。

本文件测的是**内核层**（ConversationLoop + 宿主接法），
不依赖 android/agent_bridge.py（那是 Android 专属入口，只在 android-agent 分支）。

原始缺陷：conversation_loop._success_result 返回 messages.snapshot()，
但最终那条 assistant 消息从没被 append 进 messages —— result["messages"]
缺最后一条，宿主存回 session 后下一轮就丢了 agent 的回答。
修复：成功分支先 messages.append(assistant) 再返回。
"""
from __future__ import annotations

import pytest

from conversation_loop import ConversationLoop
from tool_runner import ToolRunner


class FakeLLM:
    """记录每次收到的 messages，按轮次返回不同答案（不发真实网络请求）。"""

    def __init__(self):
        self.calls: list[list[dict]] = []

    def complete(self, messages, tools=None):
        self.calls.append([dict(m) for m in messages])
        n = len(self.calls)
        return _FakeResponse(f"第{n}轮回答")


class _FakeResponse:
    def __init__(self, content: str):
        msg = type("M", (), {"content": content, "tool_calls": None})()
        self.choices = [type("C", (), {"message": msg})()]


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def loop(fake_llm):
    return ConversationLoop(llm=fake_llm, tools=ToolRunner(), controller=None)


def _host_round(loop, session_messages, user_input):
    """模拟宿主（session_manager）的接法：跑一轮，把 result["messages"] 存回 session。"""
    result = loop.run(user_input, initial_messages=session_messages)
    return result, result.get("messages", [])


def test_result_messages_contains_final_assistant(loop):
    """根因直测：result["messages"] 必须包含 agent 自己的最终回答。"""
    result = loop.run("第一个问题")

    roles = [m.get("role") for m in result["messages"]]
    assert roles[-1] == "assistant", f"最后一条不是 assistant: {roles}"
    assert result["messages"][-1].get("content") == "第1轮回答"


def test_second_turn_carries_first_turn(loop, fake_llm):
    """第 2 轮请求必须包含第 1 轮的用户输入和 assistant 回答。"""
    _, session_messages = _host_round(loop, None, "第一个问题")
    _host_round(loop, session_messages, "第二个问题")

    assert len(fake_llm.calls) == 2
    second = fake_llm.calls[1]
    roles = [m.get("role") for m in second]
    assert "user" in roles and "assistant" in roles, f"第 2 轮缺上下文: {roles}"

    contents = [str(m.get("content")) for m in second]
    assert any("第一个问题" in c for c in contents), "第 1 轮的用户提问丢了"
    assert any("第1轮回答" in c for c in contents), "第 1 轮的 assistant 回答丢了"


def test_no_role_repetition_in_history(loop, fake_llm):
    """历史接回去后不能出现两条 user 相邻（否则 OpenAI/DeepSeek 报错）。"""
    _, session_messages = _host_round(loop, None, "第一个问题")
    _host_round(loop, session_messages, "第二个问题")

    roles = [m.get("role") for m in fake_llm.calls[1]]
    for a, b in zip(roles, roles[1:]):
        assert not (a == "user" and b == "user"), f"两条 user 相邻: {roles}"
        assert not (a == "assistant" and b == "assistant"), f"两条 assistant 相邻: {roles}"


def test_fresh_session_carries_no_history(loop, fake_llm):
    """不传 initial_messages（全新会话）时，第 1 轮只有 system + user。"""
    loop.run("第一个问题")

    roles = [m.get("role") for m in fake_llm.calls[0]]
    assert roles == ["system", "user"], f"全新会话不该带历史: {roles}"


def test_tool_schema_not_duplicated_across_turns(loop, fake_llm):
    """跑多轮后，发给 LLM 的 tools 数组不能出现重名工具。

    注册表是模块级全局的 —— 宿主反复注册/复用时，不幂等就会重名，
    openai SDK 会报 "Duplicate function names"。
    """
    _, session_messages = _host_round(loop, None, "第一个问题")
    _host_round(loop, session_messages, "第二个问题")

    for call in fake_llm.calls:
        schemas = loop.tools.schemas()
        names = [s["function"]["name"] for s in schemas]
        assert len(names) == len(set(names)), f"tools 有重名: {names}"

"""
test_compress_if_needed.py — 回归测试：压缩后不产生'孤儿'tool 消息。

bug 触发（commit 5 之前）：
  V2 用 superpowers 跑"Let's make a react todo list"——模型调
  brainstorming + 多轮 read/find/bash，超过 max_context_tokens 触发
  压缩。压缩后消息流里出现 role=tool 但没对应 assistant[tool_calls]
  的孤儿消息，DeepSeek 拒绝并报：
    'tool must be a response to a preceding message with tool_calls'

修复（commit 5）：
  message_store.compress_if_needed 改为按"原子块"切分：每个块 =
  assistant[tool_calls] + N 个 tool，块要么全丢要么全留，绝不拆散。
"""

from __future__ import annotations

import sys
sys.path.insert(0, "/root/projects/minimal-agent-v2")

from message_store import MessageStore


def _make_messages(num_blocks: int = 8) -> list[dict]:
    """构造 N 个完整块，每块 = assistant(tool_calls) + 3 个 tool 消息。

    用完这些块足以触发压缩（approximate_tokens 远超默认 8000）。
    """
    msgs = [
        {"role": "system", "content": "you are a helpful assistant"},
        {"role": "user", "content": "first question"},
    ]
    for i in range(num_blocks):
        msgs.append({
            "role": "assistant",
            "content": f"thinking step {i}",
            "tool_calls": [{
                "id": f"call_{i}_1",
                "type": "function",
                "function": {"name": "read", "arguments": '{"path":"a"}'},
            }, {
                "id": f"call_{i}_2",
                "type": "function",
                "function": {"name": "read", "arguments": '{"path":"b"}'},
            }, {
                "id": f"call_{i}_3",
                "type": "function",
                "function": {"name": "bash", "arguments": '{"command":"ls"}'},
            }],
        })
        for j in range(3):
            msgs.append({
                "role": "tool",
                "tool_call_id": f"call_{i}_{j+1}",
                "content": f"result of tool {i}.{j+1}",
            })
        msgs.append({"role": "user", "content": f"next step {i}"})
        msgs.append({"role": "assistant", "content": f"summary {i}"})
    return msgs


def _check_no_orphan_tool(msgs: list[dict]) -> tuple[bool, str]:
    """断言：每条 role=tool 消息的前一条必须是 assistant[tool_calls]，
    且 tool_call_id 在该 assistant 的 tool_calls 列表里。"""
    for i, msg in enumerate(msgs):
        if msg.get("role") != "tool":
            continue
        # 往前找最近的 assistant
        j = i - 1
        while j >= 0 and msgs[j].get("role") != "assistant":
            j -= 1
        if j < 0:
            return False, f"tool msg at {i} has no preceding assistant"
        prev = msgs[j]
        if not prev.get("tool_calls"):
            return False, f"tool msg at {i} preceded by assistant without tool_calls"
        tcid = msg.get("tool_call_id")
        valid_ids = {tc["id"] for tc in prev["tool_calls"]}
        if tcid not in valid_ids:
            return False, f"tool_call_id {tcid!r} not in {valid_ids}"
    return True, ""


def test_compress_preserves_tool_pairs():
    """压缩后所有 tool 消息必须有对应 assistant[tool_calls]。"""
    ms = MessageStore()
    for msg in _make_messages(num_blocks=10):
        ms.append(msg)

    # 触发压缩（max_tokens 远小于消息体实际估算值）
    # approximate_tokens 用 len/2 算，10 块 ≈ 665 tokens
    compressed = ms.compress_if_needed(max_tokens=200)
    assert compressed, "expected compression to trigger with so many blocks"

    ok, reason = _check_no_orphan_tool(ms.all())
    assert ok, f"orphan tool message after compression: {reason}"


def test_compress_keeps_tail_blocks_intact():
    """压缩保留尾部 3 个块，必须整块存在。"""
    ms = MessageStore()
    msgs = _make_messages(num_blocks=10)
    for msg in msgs:
        ms.append(msg)
    original_tail_size = len(msgs)  # 期望最后 3 个块完整保留

    ms.compress_if_needed(max_tokens=2000)

    # 找出尾部块的 tool 消息，确认配对
    kept = ms.all()
    # 至少最后 3 个 assistant[tool_calls] 应该带 3 个 tool 消息
    last_assistants = [
        m for m in kept
        if m.get("role") == "assistant" and m.get("tool_calls")
    ][-3:]
    assert len(last_assistants) == 3, f"expected 3 tail assistant blocks, got {len(last_assistants)}"

    # 每个 tail assistant 之后应该有 3 个 tool 消息
    for asst in last_assistants:
        idx = kept.index(asst)
        tool_msgs = [m for m in kept[idx+1:idx+4] if m.get("role") == "tool"]
        assert len(tool_msgs) == 3, \
            f"tail assistant {asst['tool_calls'][0]['id']} has {len(tool_msgs)} tool msgs, expected 3"


def test_compress_under_threshold_is_noop():
    """未超 max_tokens 时不压缩。"""
    ms = MessageStore()
    msgs = _make_messages(num_blocks=2)
    for msg in msgs:
        ms.append(msg)

    before_len = len(ms.all())
    compressed = ms.compress_if_needed(max_tokens=100000)
    after_len = len(ms.all())

    assert not compressed
    assert before_len == after_len


def test_compress_with_orphan_tool_handled():
    """防御性：消息流开头就有孤儿 tool 消息（异常输入）—— 不崩，能保留。"""
    ms = MessageStore()
    ms.append({"role": "system", "content": "sys"})
    ms.append({"role": "tool", "tool_call_id": "orphan_call", "content": "orphan result"})
    # 后面接一个正常块
    ms.append({
        "role": "assistant",
        "content": "thinking",
        "tool_calls": [{
            "id": "good_call",
            "type": "function",
            "function": {"name": "bash", "arguments": "{}"},
        }],
    })
    ms.append({"role": "tool", "tool_call_id": "good_call", "content": "ok"})
    ms.append({"role": "user", "content": "continue"})

    # 重复几轮以触发压缩
    for _ in range(20):
        ms.append({
            "role": "assistant",
            "content": "more thinking",
            "tool_calls": [{
                "id": f"call_{_}",
                "type": "function",
                "function": {"name": "ls", "arguments": "{}"},
            }],
        })
        ms.append({"role": "tool", "tool_call_id": f"call_{_}", "content": "result"})

    # 不应该崩
    compressed = ms.compress_if_needed(max_tokens=2000)
    assert isinstance(compressed, bool)


if __name__ == "__main__":
    # 不用 pytest 直接跑也 OK
    test_compress_preserves_tool_pairs()
    print("✓ test_compress_preserves_tool_pairs")
    test_compress_keeps_tail_blocks_intact()
    print("✓ test_compress_keeps_tail_blocks_intact")
    test_compress_under_threshold_is_noop()
    print("✓ test_compress_under_threshold_is_noop")
    test_compress_with_orphan_tool_handled()
    print("✓ test_compress_with_orphan_tool_handled")
    print("\nAll 4 tests passed.")

#!/usr/bin/env python3
"""
message_store.py — 模块 4/5：消息仓库（MessageStore）
=======================================================

Hermes 对应: 没有独立文件，逻辑散在 conversation_loop.py 的 messages 操作中
            （append assistant / append tool / 压缩前后快照 / 会话持久化）

职责：所有对 messages 列表的"增删改查"都经过这里，循环本身不直接碰列表。

教学要点：
  这是"5 模块拆分"里最容易被忽视、但最重要的一个——
  5000 行循环里大量代码其实是在做"消息管理"（压缩、快照、持久化、
  超长截断）。拆出来之后，循环骨架只剩 append/compress 两个动作。
"""

from __future__ import annotations

from typing import Any, Optional


class MessageStore:
    """消息列表的唯一入口。循环通过它读写消息。"""

    def __init__(self, messages: Optional[list[dict]] = None):
        self._messages: list[dict] = list(messages) if messages else []

    # ── 读 ──────────────────────────────────────────────────────────────

    def all(self) -> list[dict]:
        """返回当前全部消息（浅拷贝，防止外部误改）。"""
        return list(self._messages)

    def snapshot(self) -> list[dict]:
        """深快照，用于持久化/调试。

        Hermes 对应: 会话写入 session JSON 前的 _session_messages 快照。
        """
        import copy
        return copy.deepcopy(self._messages)

    def last(self) -> Optional[dict]:
        return self._messages[-1] if self._messages else None

    def count(self) -> int:
        return len(self._messages)

    # ── 写 ──────────────────────────────────────────────────────────────

    def append(self, message: dict) -> None:
        """追加一条消息。"""
        self._messages.append(message)

    def append_tool_result(self, tool_call_id: str, content: str) -> None:
        """追加一条 role=tool 的结果消息（工具执行后回填）。

        Hermes 对应: conversation_loop.py 中 _execute_tool_calls 之后
        messages.append({"role": "tool", "tool_call_id": ..., "content": ...})
        """
        self._messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        })

    def append_assistant_with_tool_calls(self, assistant_dict: dict) -> None:
        """追加一条带 tool_calls 的 assistant 消息（规范化后的 dict）。"""
        self._messages.append(assistant_dict)

    # ── 压缩 / 超长处理（Hermes 的核心痛点）────────────────────────────

    def approximate_tokens(self) -> int:
        """粗略估算当前消息总 token 数（教学版用字符数/2.5 近似）。

        Hermes 对应: estimate_request_tokens_rough() — 更精确的估算。
        教学版够用即可——真实估算要考虑 tools、图片、缓存等。
        """
        total = 0
        for m in self._messages:
            content = m.get("content", "")
            if isinstance(content, str):
                total += len(content)
            elif isinstance(content, list):
                for p in content:
                    if isinstance(p, dict):
                        total += len(str(p.get("text", "")))
            # tool_calls 的参数字符串也算
            for tc in m.get("tool_calls", []) or []:
                total += len(tc.get("function", {}).get("arguments", ""))
        return max(1, total // 2)  # 粗略：2 字符 ≈ 1 token

    def compress_if_needed(self, max_tokens: int) -> bool:
        """如果超长，截断中间的历史消息（保留 system + 最近的 N 条）。

        Hermes 对应: _compress_context() + context_compressor — 真正的压缩
        是 LLM 摘要旧消息。教学版用"丢中间"近似，原理一致：保住头尾。

        Returns: 是否发生了压缩。
        """
        if self.approximate_tokens() <= max_tokens:
            return False

        # 保留 system（第 0 条）+ 最近的 8 条，丢掉中间的
        head = self._messages[:1]          # system
        tail = self._messages[-8:]         # 最近的 8 条
        dropped = len(self._messages) - len(head) - len(tail)
        self._messages = head + tail
        if dropped > 0:
            self._messages.insert(1, {
                "role": "system",
                "content": f"[教学版压缩提示：已丢弃中间 {dropped} 条历史消息]",
            })
        return True

    # ── 调试 ─────────────────────────────────────────────────────────────

    def pprint(self, limit: int = 200) -> None:
        """打印当前消息列表（截断长内容），供 verbose 模式使用。"""
        for i, msg in enumerate(self._messages):
            role = msg["role"].ljust(10)
            if role.strip() == "tool":
                content = (msg.get("content", "") or "")[:limit]
                cid = msg.get("tool_call_id", "")[:6]
                print(f"  [{i}] {role} tool_result({cid}...) = {content!r}")
            elif msg.get("tool_calls"):
                names = [t["function"]["name"] for t in msg["tool_calls"]]
                print(f"  [{i}] {role} tool_calls={names}")
                for t in msg["tool_calls"]:
                    print(f"        {t['function']['name']}({t['function']['arguments']})")
            else:
                content = (msg.get("content") or "")[:limit]
                print(f"  [{i}] {role} content={content!r}")

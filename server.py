#!/usr/bin/env python3
"""
server.py — ragbook agent 内核服务（minimal-agent-v2 分支 ragbook-kernel）

替代 rag-on-book web.py 的手写管道后端：
  旧内核：意图分类 → meta/闲聊/提问三路 → 拼 prompt → 单轮 LLM（2 轮历史窗口）
  新内核：ConversationLoop 多轮 tool 循环，模型自己决定调什么工具

API 契约与 web.py 完全兼容（前端零改动）：
  /            前端（复用 web.INDEX_HTML）
  /api/books   书清单（复用 web.api_books）
  /api/ask     **替换点**：V2 内核 + 读书工具集
  /api/sessions* 会话 CRUD（复用 web.*，同一 sessions.db）
  /api/source  原文抽屉（复用 web.api_source）

coding 工具（write/bash/read/...）一个都不挂载 —— tools.py 不被 import。
"""
from __future__ import annotations

import json
import os
import sys
import time

WORKTREE = os.path.dirname(os.path.abspath(__file__))
RAGBOOK_DIR = os.environ.get("RAGBOOK_DIR", "/root/projects/rag-on-book")
sys.path.insert(0, WORKTREE)          # V2 内核模块（tool_runner / conversation_loop / ...）
sys.path.insert(0, RAGBOOK_DIR)       # ragbook 检索层（books / ask / web）—— 排在后面，重名让位给内核

from flask import Flask, jsonify, request, Response  # noqa: E402

import tool_runner                    # noqa: E402
import ragbook_tools                  # noqa: E402  # import 即注册读书工具（幂等）
import web as web_mod                 # noqa: E402  # ragbook 会话层 + 前端 + 原文 API
import books as books_mod             # noqa: E402

from llm_client import LLMClient          # noqa: E402
from conversation_loop import ConversationLoop  # noqa: E402
from tool_runner import ToolRunner        # noqa: E402
from loop_controller import LoopController  # noqa: E402

# ---------- LLM 配置（收敛在顶部） ----------

MODEL = os.environ.get("RAGBOOK_AGENT_MODEL", "deepseek-chat")
BASE_URL = os.environ.get("RAGBOOK_AGENT_BASE_URL", "https://api.deepseek.com/v1")
MAX_TURNS = int(os.environ.get("RAGBOOK_AGENT_MAX_TURNS", "8"))
HISTORY_CAP = 40          # 带给内核的历史消息上限（旧内核只有 4 条）

PORT = int(os.environ.get("RAGBOOK_AGENT_PORT", "83"))


def _load_env_keys() -> None:
    """把 ~/.hermes/.env 的 KEY=VALUE 读进环境（不覆盖已有）。不打印任何值。"""
    env_path = os.path.expanduser("~/.hermes/.env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


_load_env_keys()


def _llm() -> LLMClient:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise RuntimeError("未找到 DEEPSEEK_API_KEY（~/.hermes/.env 或环境变量）")
    return LLMClient(model=MODEL, base_url=BASE_URL, api_key=api_key)


# ---------- system prompt（读书搭子 + 工具使用规则） ----------

def _system_prompt(book_id: str) -> str:
    try:
        m = books_mod.get_book(book_id)
        display, author = web_mod.ask_mod.book_context(book_id)
    except Exception:
        display, author = book_id, ""
    who = f"{display}（{author}）" if author else display
    return f"""你是「{who}」的读书搭子，帮助用户读这本书、回答关于书内容的问题。

当前数据源是《{display}》。可用工具：
- search_book：语义检索（概念、解释、跨章节找内容）
- lookup_section：按章节号/章节名/主题名精确召回（用户明确问某章/某主题时优先用）
- read_source：读某条引用的完整原文（需要更多上下文时用）
- list_books / switch_book：查看或切换数据源（用户想换书时用）
- deepseek_search / deepseek_fetch：联网搜索（**只**在书里确实没有答案、且问题需要外部事实时用）

回答规则：
1. 回答要基于工具返回的书内原文，引用时用 [N] 标注（N 是工具观测里 hits 的 i 序号）。
2. 不确定书里有没有答案时先检索，不要凭空编造书的内容。
3. 用户闲聊/打招呼时正常聊天，不必强行检索。
4. 回答用中文，结构清晰，长度与问题匹配。"""


# ---------- Flask 应用（API 契约兼容 web.py） ----------

app = Flask(__name__)


@app.route("/")
def index():
    return Response(web_mod.INDEX_HTML, mimetype="text/html")


@app.route("/api/books")
def api_books():
    return web_mod.api_books()


@app.route("/api/outline/<book_id>")
def api_outline(book_id):
    return web_mod.api_outline(book_id)


@app.route("/api/sessions", methods=["GET"])
def api_sessions_list():
    return web_mod.api_sessions_list()


@app.route("/api/sessions", methods=["POST"])
def api_sessions_create():
    return web_mod.api_sessions_create()


@app.route("/api/sessions/<sid>", methods=["DELETE"])
def api_sessions_delete(sid):
    return web_mod.api_sessions_delete(sid)


@app.route("/api/session/<sid>/rename", methods=["POST"])
def api_sessions_rename(sid):
    return web_mod.api_sessions_rename(sid)


@app.route("/api/session/<sid>")
def api_session(sid):
    return web_mod.api_session(sid)


@app.route("/api/source/<book_id>/<path:rel>")
def api_source(book_id, rel):
    return web_mod.api_source(book_id, rel)


@app.route("/healthz")
def healthz():
    return jsonify({
        "ok": True,
        "kernel": "minimal-agent-v2 ragbook-kernel",
        "model": MODEL,
        "tools": list(ragbook_tools.RAGBOOK_TOOL_NAMES),
        "db": web_mod.DB_PATH,
        "model_loaded": web_mod._model is not None,
    })


# ---------- 核心替换点：/api/ask 走 V2 内核 ----------

def _extract_hits_from_turn(messages: list[dict]) -> list[dict]:
    """从本轮消息里提取最后一次检索工具的 hits（前端引用块的数据来源）。

    工具观测是 JSON 字符串（ragbook_tools._fmt_hits 的输出），
    取**最后一次** search_book / lookup_section 的结果。
    """
    for msg in reversed(messages):
        if msg.get("role") != "tool":
            continue
        try:
            data = json.loads(msg.get("content") or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and isinstance(data.get("hits"), list) and data["hits"]:
            # 观测里的 hit 已是 _hits_clean 口径（snippet），无需再清洗
            return [{
                "score": h.get("score", 0),
                "book": data.get("book", ""),
                "heading_path": h.get("heading_path", ""),
                "source": h.get("source", ""),
                "snippet": h.get("snippet", ""),
            } for h in data["hits"]]
    return []


@app.route("/api/ask", methods=["POST"])
def api_ask():
    data = web_mod._parse_json_body()
    query = (data.get("query") or "").strip()
    sid_in = data.get("session_id")
    book_id = data.get("book") or None

    if not query:
        return jsonify({"error": "query 不能为空"}), 400

    book = web_mod._resolve_book(book_id)
    if book is None:
        return jsonify({"error": "没有可用的书（先跑 parse.py + index.py）"}), 503
    book_id = book["id"]

    sid = web_mod.get_or_create_session(sid_in, book=book_id)

    # 当前数据源 = 请求指定的书（switch_book 可在会话中途改）
    ragbook_tools.set_current_book(book_id)

    # 完整历史进内核（旧内核只带 4 条）—— 上限 HISTORY_CAP 防超长
    history = [
        {"role": m["role"], "content": m["content"]}
        for m in web_mod.get_messages(sid)
        if m["role"] in ("user", "assistant")
    ][-HISTORY_CAP:]

    t0 = time.time()
    try:
        loop = ConversationLoop(
            llm=_llm(),
            tools=ToolRunner(verbose=False),
            controller=LoopController(max_turns=MAX_TURNS, verbose=False),
            max_context_tokens=100000,
        )
        result = loop.run(
            query,
            system_prompt=_system_prompt(book_id),
            initial_messages=history,
        )
    except Exception as e:
        return jsonify({"error": f"内核执行失败: {e}"}), 500
    llm_ms = int((time.time() - t0) * 1000)

    answer = (result.get("final_response") or "").strip() or "（内核未返回正文）"
    hits = _extract_hits_from_turn(result.get("messages") or [])

    web_mod.add_message(sid, "user", query)
    web_mod.add_message(sid, "assistant", answer, hits=hits, llm_ms=llm_ms)
    web_mod.auto_title_if_new(sid, query)

    return jsonify({
        "session_id": sid,
        "answer": answer,
        "hits": hits,
        "search_ms": 0,
        "llm_ms": llm_ms,
        "book": book_id,
        "intent": "agent",
        "intent_src": "kernel",
        "agent_stats": {
            "api_calls": result.get("api_calls", 0),
            "tool_calls": result.get("tool_calls", 0),
            "exit_reason": result.get("exit_reason", ""),
        },
    })


if __name__ == "__main__":
    web_mod.init_db()
    print(f"ragbook agent kernel: port={PORT} model={MODEL} tools={len(tool_runner._TOOL_SCHEMAS)}")
    app.run(host="127.0.0.1", port=PORT, threaded=True)

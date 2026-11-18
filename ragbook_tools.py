#!/usr/bin/env python3
"""
ragbook_tools.py — 把 rag-on-book 的检索能力包装成 agent 工具集

数据源 = 一本书。switch_book 切换当前书后，所有检索工具都打向那本书
自己的向量库（一书一库，见 rag-on-book books.py）。

工具清单（coding 工具一个都没有 —— 本模块只注册下面这些）：
  list_books     列出所有可选书
  switch_book    切换当前数据源（书）
  search_book    当前书内向量语义检索
  lookup_section 章节/主题级精确召回（元信息过滤，不调 embedding）
  read_source    读某节完整原文
  deepseek_search / deepseek_fetch   联网兜底（书里没有的）

复用约定：检索函数单一来源在 rag-on-book（web.py / ask.py / books.py），
本模块只做包装和观测格式化，不重复实现检索逻辑。
"""
from __future__ import annotations

import json
import os
import re
import sys

# ragbook 项目根（books.py / index.py / ask.py / web.py 的单一来源）
RAGBOOK_DIR = os.environ.get("RAGBOOK_DIR", "/root/projects/rag-on-book")
if RAGBOOK_DIR not in sys.path:
    sys.path.insert(0, RAGBOOK_DIR)

from tool_runner import register_external  # noqa: E402  (V2 内核)

import books as books_mod            # noqa: E402
import ask as ask_mod                # noqa: E402
import web as web_mod                # noqa: E402
import deepseek_search as ds         # noqa: E402

# ---------- 当前数据源（书）状态 ----------

_CURRENT = {"book": None}


def set_current_book(book_id: str | None) -> None:
    """宿主（server）在每次 /api/ask 时按请求设置当前书。

    switch_book 工具在会话中途切换时也走这里 —— 单一改口点。
    """
    if book_id is not None:
        books_mod.get_book(book_id)          # 校验存在性
    _CURRENT["book"] = book_id


def _require_book() -> str:
    if not _CURRENT["book"]:
        raise RuntimeError("当前没有选定的书 —— 先调 switch_book")
    return _CURRENT["book"]


def _fmt_hits(hits: list[dict], max_items: int = 8) -> list[dict]:
    """milvus 命中 → 给模型看的紧凑观测（也是前端 hits 的数据来源）。

    i 序号与模型答案里的 [N] 引用一一对应；snippet 截 240 字。
    """
    out = []
    for i, h in enumerate(hits[:max_items], start=1):
        out.append({
            "i": i,
            "score": h.get("score", 0),
            "heading_path": h.get("heading_path", ""),
            "source": h.get("source", ""),
            "snippet": (h.get("content") or "")[:240].replace("\n", " "),
        })
    return out


# ---------- 工具实现 ----------

def _list_books() -> str:
    bl = books_mod.list_books()
    return json.dumps([{
        "id": b["id"], "title": b.get("title", ""), "author": b.get("author", ""),
        "chunks": b.get("chunks", 0),
        "is_current": b["id"] == _CURRENT["book"],
    } for b in bl], ensure_ascii=False)


def _switch_book(book_id: str) -> str:
    try:
        m = books_mod.get_book(book_id)
    except books_mod.BookError as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)
    set_current_book(book_id)
    display, author = ask_mod.book_context(book_id)
    outline = web_mod.get_outline(book_id)
    n = len(outline.get("items") or [])
    return json.dumps({
        "ok": True, "book": book_id, "title": display, "author": author,
        "目录条目数": n,
        "说明": "已切换数据源。后续 search_book / lookup_section / read_source 都作用于这本书。",
    }, ensure_ascii=False)


def _search_book(query: str, top_k: int = 6) -> str:
    book_id = _require_book()
    web_mod.ensure_loaded()
    client = web_mod.get_book_client(book_id)
    hits = ask_mod.search(client, web_mod._model, query, book=book_id, top_k=top_k)
    return json.dumps({"book": book_id, "hits": _fmt_hits(hits)}, ensure_ascii=False)


def _lookup_section(target: str) -> str:
    """章节/主题精确召回。target 形如 "第8章 弱隔离级别"（章节书）
    或 "算法 - 排序"（笔记集主题名）。
    """
    book_id = _require_book()
    book = books_mod.get_book(book_id)
    meta_filter, meta_info = web_mod.detect_meta_query(target, book)
    if meta_info.get("out_of_range"):
        return json.dumps({
            "error": f"{book.get('title', book_id)} 共 {meta_info['max_chapter']} 章，没有第{meta_info['chapter']}章",
        }, ensure_ascii=False)
    if not meta_filter:
        return json.dumps({
            "error": "没有匹配到章节/主题。可用 lookup 前先看目录（switch_book 返回条目数），"
                     "或改用 search_book 做语义检索。",
        }, ensure_ascii=False)
    web_mod.ensure_loaded()
    client = web_mod.get_book_client(book_id)
    chunks = web_mod.meta_search(client, meta_filter, meta_info)
    return json.dumps({
        "book": book_id,
        "meta": {k: meta_info.get(k) for k in ("chapter", "chapter_title", "section") if meta_info.get(k)},
        "hits": _fmt_hits(chunks, max_items=10),
    }, ensure_ascii=False)


def _read_source(source: str) -> str:
    """读某节完整原文。source 形如 "content/zh/ch8.md#sec_xxx"
    （search/lookup 观测里的 source 字段）。
    """
    book_id = _require_book()
    rel = source.split("#")[0]
    base = os.path.realpath(os.path.join(books_mod.BOOKS_DIR, book_id))
    target = os.path.realpath(os.path.join(base, rel))
    if not target.startswith(base + os.sep) or not os.path.exists(target):
        return json.dumps({"error": f"文件不存在: {rel}"}, ensure_ascii=False)
    with open(target, encoding="utf-8") as f:
        md = f.read()
    md = re.sub(r"^---\s*\n.*?\n---\s*\n", "", md, count=1, flags=re.S)
    # 有锚点时尽量只返回该节附近（截不起就全文，模型自己挑重点）
    anchor = source.split("#")[1] if "#" in source else None
    if anchor:
        idx = md.find(anchor)
        if idx >= 0:
            md = md[max(0, idx - 200): idx + 6000]
    if len(md) > 12000:
        md = md[:12000] + "\n…（截断）"
    return json.dumps({"book": book_id, "source": source, "markdown": md}, ensure_ascii=False)


def _deepseek_search(query: str, count: int = 5) -> str:
    """联网搜索（deepseek tools/search）。书里没有的内容才用。"""
    try:
        r = ds.search_tool(query, count=count)
        return json.dumps(r, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"联网搜索失败: {e}"}, ensure_ascii=False)


def _deepseek_fetch(url: str) -> str:
    try:
        r = ds.fetch(url)
        return json.dumps(r, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"抓取失败: {e}"}, ensure_ascii=False)


# ---------- 注册（import 本模块即完成；幂等，宿主可反复 import） ----------

_BOOK_PARAM = {"type": "string", "description": "书 id（list_books 返回的 id）"}

register_external(
    "list_books",
    "列出所有可选的书（当前数据源会标 is_current）",
    {"type": "object", "properties": {}, "required": []},
    lambda: _list_books(),
)
register_external(
    "switch_book",
    "切换当前数据源到某本书。切换后所有检索工具都作用于这本书。",
    {"type": "object", "properties": {"book_id": _BOOK_PARAM}, "required": ["book_id"]},
    _switch_book,
)
register_external(
    "search_book",
    "在当前书的向量库里做语义检索（找概念、找解释、跨章节找内容）",
    {"type": "object", "properties": {
        "query": {"type": "string", "description": "检索问题"},
        "top_k": {"type": "integer", "description": "返回条数，默认 6"},
    }, "required": ["query"]},
    _search_book,
)
register_external(
    "lookup_section",
    "按章节号/章节名/主题名精确召回（比 search_book 更准，用户明确问某章或某主题时用）",
    {"type": "object", "properties": {
        "target": {"type": "string", "description": "如 '第8章 弱隔离级别' 或主题名 '算法 - 排序'"},
    }, "required": ["target"]},
    _lookup_section,
)
register_external(
    "read_source",
    "读某条引用的完整原文（source 字段来自 search/lookup 的观测）",
    {"type": "object", "properties": {
        "source": {"type": "string", "description": "如 'content/zh/ch8.md#sec_xxx'"},
    }, "required": ["source"]},
    _read_source,
)
register_external(
    "deepseek_search",
    "联网搜索（书里没有的时事/外部知识才用；能不用就不用）",
    {"type": "object", "properties": {
        "query": {"type": "string", "description": "搜索词，支持 site: -词 \"短语\" lang:zh 等算子"},
        "count": {"type": "integer", "description": "结果条数，默认 5"},
    }, "required": ["query"]},
    _deepseek_search,
)
register_external(
    "deepseek_fetch",
    "抓取某个网页的正文（配合 deepseek_search 的 url 使用）",
    {"type": "object", "properties": {
        "url": {"type": "string", "description": "要抓取的网页 URL"},
    }, "required": ["url"]},
    _deepseek_fetch,
)

RAGBOOK_TOOL_NAMES = ("list_books", "switch_book", "search_book", "lookup_section",
                      "read_source", "deepseek_search", "deepseek_fetch")

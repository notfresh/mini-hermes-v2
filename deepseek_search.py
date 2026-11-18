#!/usr/bin/env python3
"""
deepseek_search.py — 把 DeepSeek Search / Fetch API 包成可复用的搜索工具。

用法：
    from deepseek_search import search, fetch
    r = search("DeepSeek V4 发布时间", count=5, need_content=False)
    for x in r: print(x["title"], x["url"])

也可以当 CLI 用：
    python3 deepseek_search.py "关键词" --count 5 --content
"""
import json
import os
import urllib.error
import urllib.request

BASE = "https://api.deepseek.com"
SEARCH_PATH = "/v1/tools/search"
FETCH_PATH = "/v1/tools/fetch"
KEY_ENV = "DEEPSEEK_API_KEY"


def _key():
    k = os.environ.get(KEY_ENV)
    if k:
        return k
    dotenv = os.path.expanduser("~/.hermes/.env")
    if os.path.exists(dotenv):
        with open(dotenv) as f:
            for line in f:
                if line.startswith(KEY_ENV + "="):
                    return line.strip().split("=", 1)[1].strip().strip("\"'")
    raise RuntimeError(f"未找到 {KEY_ENV}（~/.hermes/.env 或环境变量）")


def _post(path, body, timeout=60):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {_key()}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def search(query, count=10, need_content=False, ori_question=None, localization=None, timeout=60):
    """搜网页。返回 results 列表。

    count: 1-50（默认 10）
    need_content: True 时每条结果带全文 content（较慢更贵）
    ori_question: 用户的原始问题，帮助引擎理解意图
    localization: IP 字符串，用于本地化结果
    """
    body = {"query": query, "count": count, "need_content": need_content}
    if ori_question:
        body["ori_question"] = ori_question
    if localization:
        body["localization"] = localization
    return _post(SEARCH_PATH, body, timeout=timeout).get("results", [])


def fetch(url, timeout=60):
    """抓单个网页，返回 {title, content(markdown), url, ...}。"""
    return _post(FETCH_PATH, {"url": url}, timeout=timeout)


def search_tool(query, count=5, need_content=False):
    """给 LLM tool 用的紧凑返回（省 token）。"""
    results = search(query, count=count, need_content=need_content)
    out = []
    for r in results:
        item = {
            "title": r.get("title"),
            "url": r.get("url"),
            "snippet": r.get("snippet"),
            "score": r.get("rerank_score"),
            "date": r.get("date"),
            "site": r.get("site_name"),
        }
        if need_content and r.get("content"):
            item["content"] = r["content"][:4000]
        elif r.get("summary"):
            item["summary"] = r["summary"]
        out.append(item)
    return out


# ===== OpenAI-style tool schema（可直接塞进 tools=[]）=====
SEARCH_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "搜索互联网。用 DeepSeek 官方 Search API（自研搜索引擎），"
            "返回标题/URL/摘要/日期/权威度。支持 site: -site: lang: after: before: 等算子。"
            "需要网页全文时设 need_content=true。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词，1-128 字符。支持 site:example.com / lang:zh / after:2026-01-01 等算子",
                },
                "count": {
                    "type": "integer",
                    "description": "返回条数，1-50，默认 5",
                    "default": 5,
                },
                "need_content": {
                    "type": "boolean",
                    "description": "是否抓取每个结果的网页全文（慢且贵，默认 false）",
                    "default": False,
                },
            },
            "required": ["query"],
        },
    },
}

FETCH_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_fetch",
        "description": "抓取指定网页的正文内容（返回 Markdown）。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要抓取的 http/https URL"}
            },
            "required": ["url"],
        },
    },
}


def _execute(name, args):
    """工具分发：给 tool_calls 的 function.name/arguments 用。"""
    if name == "web_search":
        return search_tool(
            query=args.get("query", ""),
            count=int(args.get("count", 5)),
            need_content=bool(args.get("need_content", False)),
        )
    if name == "web_fetch":
        page = fetch(args["url"])
        return {
            "title": page.get("title"),
            "url": page.get("url"),
            "content": (page.get("content") or "")[:8000],
        }
    raise ValueError(f"未知工具: {name}")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--content", action="store_true")
    ap.add_argument("--fetch", help="改为抓取这个 URL")
    args = ap.parse_args()

    if args.fetch:
        page = fetch(args.fetch)
        print(f"# {page.get('title')}\n\n{page.get('content','')[:5000]}")
    else:
        for r in search_tool(args.query, args.count, args.content):
            print(f"\n=== [{r.get('score')}] {r.get('title')}")
            print(f"    {r.get('url')}")
            if r.get("date"):
                print(f"    {r.get('site')} | {r.get('date')}")
            body = r.get("summary") or r.get("snippet") or ""
            print(f"    {body[:400]}")

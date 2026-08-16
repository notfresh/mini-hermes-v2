#!/usr/bin/env python3
"""
session_manager.py — Session 管理模块
======================================

职责：
- Session 生命周期管理（创建/加载/保存/删除/列表）
- REPL 主循环入口
- 提示词统一管理

存储位置：~/.minimal-agent-v2/
"""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════
# 提示词常量
# ═══════════════════════════════════════════════════════════════════════════

REPL_WELCOME = """=== MinimalAgentV2 REPL ===

可用的 sessions:"""

REPL_NO_SESSIONS = "（暂无 session）"

REPL_CHOOSE = "请选择 [1-{count}] 或输入新名字创建: "

REPL_PROMPT = "[{name}] 💬 "

REPL_HELP = """/new <名字>   - 新建 session
/switch <名字|序号> - 切换 session（序号需先 /list 查看）
/list          - 列出所有 session
/delete <名字> - 删除 session
/exit, /quit   - 退出"""

REPL_SAVED = "会话已保存。再见！"
REPL_CREATED = "已创建 session: {name}"
REPL_SWITCHED = "已切换到 session: {name}"
REPL_DELETED = "已删除 session: {name}"
REPL_NOT_FOUND = "Session 不存在: {name}"


# ═══════════════════════════════════════════════════════════════════════════
# Session 类
# ═══════════════════════════════════════════════════════════════════════════

class Session:
    """单个 session 的数据"""

    def __init__(
        self,
        name: str,
        messages: Optional[list[dict]] = None,
        created_at: Optional[str] = None,
        updated_at: Optional[str] = None,
    ):
        self.name = name
        self.messages = messages or []
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = updated_at or datetime.now().isoformat()

    def add_message(self, role: str, content: str, **kwargs) -> None:
        """追加消息"""
        msg = {"role": role, "content": content, **kwargs}
        self.messages.append(msg)
        self.updated_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "messages": self.messages,
        }

    def save(self, base_dir: Path) -> None:
        """保存到文件"""
        sessions_dir = base_dir / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        path = sessions_dir / f"{self.name}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls, path: Path) -> Session:
        """从文件加载"""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls(
            name=data["name"],
            messages=data.get("messages", []),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )


# ═══════════════════════════════════════════════════════════════════════════
# SessionManager 类
# ═══════════════════════════════════════════════════════════════════════════

class SessionManager:
    """Session 生命周期管理"""

    def __init__(self, base_dir: str = "~/.minimal-agent-v2"):
        self.base_dir = Path(base_dir).expanduser()
        self.sessions_dir = self.base_dir / "sessions"
        self.index_file = self.base_dir / "sessions.json"

    def _ensure_index(self) -> dict:
        """确保索引文件存在"""
        if not self.index_file.exists():
            self._save_index({"sessions": [], "active": None})
        return self._load_index()

    def _load_index(self) -> dict:
        with open(self.index_file, encoding="utf-8") as f:
            return json.load(f)

    def _save_index(self, index: dict) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=2)

    def list(self) -> list[str]:
        """列出所有 session"""
        index = self._ensure_index()
        return index.get("sessions", [])

    def create(self, name: str) -> Session:
        """创建新 session"""
        index = self._ensure_index()
        sessions = index.get("sessions", [])
        if name not in sessions:
            sessions.append(name)
            self._save_index({"sessions": sessions, "active": name})
        return Session(name=name)

    def load(self, name: str) -> Optional[Session]:
        """加载已有 session"""
        path = self.sessions_dir / f"{name}.json"
        if not path.exists():
            return None
        return Session.load(path)

    def delete(self, name: str) -> bool:
        """删除 session"""
        index = self._ensure_index()
        sessions = index.get("sessions", [])
        if name not in sessions:
            return False
        # 删除文件
        path = self.sessions_dir / f"{name}.json"
        if path.exists():
            path.unlink()
        # 更新索引
        sessions.remove(name)
        active = index.get("active")
        if active == name:
            active = sessions[0] if sessions else None
        self._save_index({"sessions": sessions, "active": active})
        return True

    def get_active(self) -> Optional[str]:
        """获取当前活跃 session 名"""
        index = self._ensure_index()
        return index.get("active")

    def set_active(self, name: str) -> None:
        """设置当前活跃 session"""
        index = self._ensure_index()
        index["active"] = name
        self._save_index(index)


# ═══════════════════════════════════════════════════════════════════════════
# REPL 入口
# ═══════════════════════════════════════════════════════════════════════════

def run_repl(
    tools_runner: "ToolRunner",
    llm: "LLMClient",
    verbose: bool = False,
    max_turns: int = 10,
    skills: "Optional[SkillRegistry]" = None,
) -> None:
    """REPL 主循环

    Args:
        skills: 技能注册表（技能框架挂载点；None = 不启用）
    """
    from conversation_loop import ConversationLoop
    from loop_controller import LoopController

    manager = SessionManager()
    controller = LoopController(max_turns=max_turns, verbose=verbose)
    loop = ConversationLoop(
        llm=llm,
        tools=tools_runner,
        controller=controller,
        skills=skills,
        verbose=verbose,
    )

    # 1. 显示欢迎 + session 列表
    print(REPL_WELCOME)
    sessions = manager.list()
    if sessions:
        for i, name in enumerate(sessions, 1):
            active = " *" if name == manager.get_active() else ""
            print(f"  {i}. {name}{active}")
    else:
        print(REPL_NO_SESSIONS)

    # 2. 获取用户选择
    name = _choose_session(manager, sessions)
    session = manager.load(name)
    if session is None:
        # 纯内存创建：未开始聊天不落盘，第一条对话时才持久化
        session = Session(name=name)
        print(REPL_CREATED.format(name=name))
    else:
        manager.set_active(name)

    # 3. REPL 循环
    while True:
        try:
            user_input = input(REPL_PROMPT.format(name=session.name)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        
        # 退出命令
        if user_input.lower() in ("/exit", "/quit"):
            print("退出 REPL。")
            if session.messages:
                session.save(manager.base_dir)
                print(REPL_SAVED)
            else:
                print("未开始聊天，未保存。再见！")
            break
        
        # 处理命令
        if user_input.startswith("/"):
            new_session = _handle_command(user_input, session, manager, loop)
            if new_session is not None:
                session = new_session
            continue



        # 正常对话
        result = loop.run(
            user_message=user_input,
            initial_messages=session.messages,
        )

        # 保存结果到 session（第一次真实对话才注册索引 + 落盘，幂等）
        session.messages = result.get("messages", [])
        manager.create(session.name)
        session.save(manager.base_dir)

        # 显示回复
        print(f"🤖: {result['final_response']}")
        if verbose:
            print(f"  [api_calls={result['api_calls']}, tool_calls={result['tool_calls']}]")


def _choose_session(manager: SessionManager, sessions: list[str]) -> str:
    """让用户选择或创建 session"""
    if not sessions:
        name = input("输入新 session 名字: ").strip()
        return name or "default"

    prompt = REPL_CHOOSE.format(count=len(sessions))
    while True:
        choice = input(prompt).strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(sessions):
                return sessions[idx]
        # 认为是新名字
        return choice


def _resolve_target(manager: SessionManager, ref: str) -> Optional[str]:
    """把 /switch 的参数解析成 session 名。

    参数是纯数字时，按 manager.list() 的 1 起始序号映射（与 /list 一致）；
    否则视为名字原样返回。序号越界或映射不到时返回 None。
    """
    if not ref.isdigit():
        return ref
    sessions = manager.list()
    idx = int(ref) - 1
    if 0 <= idx < len(sessions):
        return sessions[idx]
    return None


def _handle_command(
    user_input: str,
    session: Session,
    manager: SessionManager,
    loop: "ConversationLoop",
) -> Optional[Session]:
    """处理 REPL 命令

    返回：
        新 session 或 None。/new、/switch 切换了当前 session 时返回新 session，
        REPL 主循环据此更新提示符名字；其余命令返回 None。
    """
    parts = user_input.split(maxsplit=1)
    cmd = parts[0]
    arg = parts[1] if len(parts) > 1 else None

    if cmd == "/list":
        sessions = manager.list()
        if not sessions:
            print(REPL_NO_SESSIONS)
            return None
        for i, name in enumerate(sessions, 1):
            active = " *" if name == manager.get_active() else ""
            print(f"  {i}. {name}{active}")

    elif cmd == "/new":
        if not arg:
            print("用法: /new <名字>")
            return None
        # 纯内存创建：未开始聊天不落盘，第一条对话时才持久化
        new_session = Session(name=arg)
        print(REPL_CREATED.format(name=arg))
        return new_session

    elif cmd == "/switch":
        if not arg:
            print("用法: /switch <名字|序号>")
            return None
        target = _resolve_target(manager, arg)
        if target is None:
            print(f"Session 不存在: {arg}")
            return None
        if manager.load(target) is None:
            print(REPL_NOT_FOUND.format(name=target))
            return None
        # 当前 session 聊过才保存；没聊过不落盘（不产生多余文件）
        if session.messages:
            session.save(manager.base_dir)
        # 切换
        manager.set_active(target)
        new_session = manager.load(target)
        print(REPL_SWITCHED.format(name=target))
        return new_session

    elif cmd == "/delete":
        if not arg:
            print("用法: /delete <名字>")
            return None
        if manager.delete(arg):
            print(REPL_DELETED.format(name=arg))
        else:
            print(REPL_NOT_FOUND.format(name=arg))

    elif cmd in ("/help", "/h"):
        print(REPL_HELP)

    else:
        print(f"未知命令: {cmd}")
        print(REPL_HELP)
    return None

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
/plan          - 进入规划模式（只读调研 + 只能写计划文件）
/approve       - 批准当前计划（批准后模型才能退出规划模式开始执行）
/revise <反馈> - 要求模型按反馈修改计划并重新提交
/run           - 已批准后退出规划模式，开始执行
/cancel        - 取消当前计划并退出规划模式
/exit, /quit   - 退出"""

REPL_SAVED = "会话已保存。再见！"
REPL_CREATED = "已创建 session: {name}"
REPL_SWITCHED = "已切换到 session: {name}"
REPL_DELETED = "已删除 session: {name}"
REPL_HISTORY_EMPTY = "（该 session 暂无可打印的对话历史）"
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

    def add_session(self, session: Session) -> Session:
        """添加已有 session"""
        index = self._ensure_index()
        sessions = index.get("sessions", [])
        if session.name not in sessions:
            sessions.append(session.name)
            self._save_index({"sessions": sessions, "active": session.name})
        return session

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
        _print_history(session) 
        manager.set_active(name)
        
    # 3. REPL 循环
    while True:
        try:
            _maybe_print_plan_banner()                 # ← 新增：plan 模式时打印当前计划
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

        # Plan Mode 命令：用户手动进入/退出规划模式（人类介入入口）
        if user_input.lower() == "/plan":
            print(_process_plan_command())
            continue

        if user_input.lower() == "/run":
            print(_process_run_command())
            continue

        # Plan Mode 审批命令（/approve / /revise / /cancel）— 新增 ──
        processed = _process_user_input(user_input)
        if processed is None:
            continue
        user_input = processed

        # 处理命令
        if user_input.startswith("/"):
            new_session = _handle_command(user_input, session, manager, loop)
            if new_session is not None:
                session = new_session
            continue



        # 正常对话
        from turn_context import plan_status_line
        plan_prefix = plan_status_line()  # 规划模式激活时注入状态（模型可见）
        result = loop.run(
            user_message=plan_prefix + user_input,
            initial_messages=session.messages,
        )
        
        # 保存结果到 session（第一次真实对话才注册索引 + 落盘，幂等）
        session = manager.add_session(session)
        session.messages = result.get("messages", [])
        session.updated_at = datetime.now().isoformat()
        session.add_message("assistant", result.get("final_response", "")) # 保存 assistant 回复
        session.save(manager.base_dir)

        # 显示回复
        print(f"🤖: {result['final_response']}")
        if verbose:
            print(f"  [api_calls={result['api_calls']}, tool_calls={result['tool_calls']}]")


def _maybe_print_plan_banner() -> None:
    """plan_mode 激活且计划文件存在时，打印当前计划内容供用户审查。

    静默处理 IO 错误（不影响 REPL 主循环）。
    调用时机：在 run_repl 主循环读 input() 之前。
    """
    from plan_mode import plan_mode
    if not plan_mode.is_active:
        return
    if plan_mode.plan_path is None or not plan_mode.plan_path.exists():
        return
    try:
        content = plan_mode.plan_path.read_text(encoding="utf-8")
    except OSError:
        return
    print(f"\n📋 当前计划（{plan_mode.status_label} | {plan_mode.plan_path}）:")
    print("─" * 60)
    print(content if content else "<空>")
    print("─" * 60)


def _process_plan_command() -> str:
    """/plan：手动进入规划模式（人类介入入口）。返回提示文本。"""
    from plan_mode import plan_mode
    try:
        path = plan_mode.enter()
        return (
            f"📋 已进入规划模式，计划文件：{path}\n"
            "   现在描述任务，让模型调研并写计划（规划模式下只能写计划文件）。\n"
            "   计划写好后输入 /approve 批准，模型即可开始执行。"
        )
    except RuntimeError:
        return (
            f"⚠️ 已在规划模式中（计划文件：{plan_mode.plan_path}），"
            "用 /run 或 /cancel 退出。"
        )


def _process_run_command() -> str:
    """/run：退出规划模式开始执行（人类可强制，但未批准会提示）。返回提示文本。"""
    from plan_mode import plan_mode
    if not plan_mode.is_active:
        return "ℹ️ 当前不在规划模式（输入 /plan 进入）。"
    if plan_mode.status == plan_mode.STATUS_APPROVED:
        plan_mode.exit()
        return "▶️ 已退出规划模式，所有工具恢复可用。开始执行计划。"
    return (
        f"ℹ️ 计划尚未批准（当前状态：{plan_mode.status_label}）。"
        "输入 /approve 批准后执行；/revise <反馈> 修改计划；/cancel 取消。"
    )


def _process_user_input(user_input: str) -> Optional[str]:
    """处理 plan 审批 slash 命令（/approve / /revise / /cancel）。

    返回值：
      - None：REPL 应跳过当前输入（continue）
      - 字符串：替换 user_input 为该值注入对话（可能是合成消息）

    V3：审批命令驱动状态机（approve → approved / revise → planning），
    不再只是注入提示词——框架状态与用户命令同步。
    """
    # /approve
    if user_input.lower() == "/approve":
        from plan_mode import plan_mode
        if not plan_mode.is_active:
            print("ℹ️  当前不在规划模式。")
            return None
        try:
            plan_mode.approve()
        except RuntimeError as e:
            print(f"⚠️  {e}")
            return None
        print("✅ 计划已批准，模型可调 exit_plan_mode 开始执行。")
        return "✓ 计划已批准，请调 exit_plan_mode 开始执行。"

    # /revise
    if user_input.lower().startswith("/revise"):
        from plan_mode import plan_mode
        feedback = user_input[len("/revise"):].strip()
        if not plan_mode.is_active:
            print("ℹ️  当前不在规划模式（输入 /plan 进入）。")
            return None
        if not feedback:
            print("用法：/revise <反馈内容>")
            return None
        plan_mode.revise()  # 状态打回 planning：必须重写后重新提交
        print(f"📝 已要求修改计划（状态回到「规划中」，模型将重写后重新提交）。")
        return f"📝 请按反馈修改计划（用 write_plan 重新提交）：{feedback}"

    # /cancel
    if user_input.lower() == "/cancel":
        from plan_mode import plan_mode
        if plan_mode.is_active:
            plan_mode.cancel()  # 清空状态回 idle，计划文件保留（审计）
            print("✗ 已取消计划，退出规划模式。")
        else:
            print("ℹ️  当前不在规划模式。")
        return None

    # 非审批命令，原样返回
    return user_input


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


def _cancel_plan_if_active(reason: str) -> None:
    """防御：plan 激活时自动取消（切换/新建会话前调用，防跨会话串状态）。

    静默：未激活时什么都不做。
    """
    from plan_mode import plan_mode
    if plan_mode.is_active:
        plan_mode.cancel()
        print(f"ℹ️  {reason}：已自动退出规划模式（计划取消，文件保留）。")


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


def _print_history(session: Session) -> None:
    """打印某 session 的对话历史（只展示 user/assistant，隐藏工具/系统轮次）。"""
    shown = [m for m in session.messages if m.get("role") in ("user", "assistant")]
    if not shown:
        print(REPL_HISTORY_EMPTY)
        return
    print(f"── 历史对话 ({len(shown)} 条) ──")
    for i, m in enumerate(shown, 1):
        role = "💬" if m.get("role") == "user" else "🤖"
        content = m.get("content", "")
        if not isinstance(content, str):
            content = str(content)
        print(f"  [{i}] {role}: {content}")


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
        # 防御：切换/新建会话时若规划模式激活，自动取消（plan 状态是模块级单例，防串味）
        _cancel_plan_if_active("新建会话")
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
        # 防御：切换会话时若规划模式激活，自动取消（防跨会话串状态）
        _cancel_plan_if_active("切换会话")
        # 当前 session 聊过才保存；没聊过不落盘（不产生多余文件）
        if session.messages:
            session.save(manager.base_dir)
        # 切换
        manager.set_active(target)
        new_session = manager.load(target)
        print(REPL_SWITCHED.format(name=target))
        _print_history(new_session)
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

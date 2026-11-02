"""register_external —— 外部 schema 注册的测试。

背景: Android 集成里工具 schema 的单一来源在 Java 侧(AgentToolRegistry,
跟 DAO 同源),Python 侧启动时拉取后用 register_external 注入,
避免在 Python 和 Java 两处手抄同一份 schema。

覆盖:
  - schema 原样落进 _TOOL_SCHEMAS(名字/描述/parameters 不被改写)
  - 注册的工具能被 ToolRunner.execute 调到,参数按 kwargs 传进去
  - 注册表可被清空重置(测试隔离)
"""
from __future__ import annotations

import pytest

from tool_runner import ToolRunner, register_external, _TOOL_REGISTRY, _TOOL_SCHEMAS


@pytest.fixture(autouse=True)
def clean_registry():
    """每个测试前后清空注册表,避免互相污染。"""
    saved_schemas = list(_TOOL_SCHEMAS)
    saved_registry = dict(_TOOL_REGISTRY)
    _TOOL_SCHEMAS.clear()
    _TOOL_REGISTRY.clear()
    yield
    _TOOL_SCHEMAS.clear()
    _TOOL_SCHEMAS.extend(saved_schemas)
    _TOOL_REGISTRY.clear()
    _TOOL_REGISTRY.update(saved_registry)


def test_register_external_keeps_schema_verbatim():
    params = {
        "type": "object",
        "properties": {"link_id": {"type": "number", "description": "链接 id"}},
        "required": ["link_id"],
    }
    schema = register_external(
        name="get_link",
        description="按 id 读链接",
        parameters=params,
        fn=lambda **kw: "ok",
    )

    assert schema["type"] == "function"
    assert schema["function"]["name"] == "get_link"
    assert schema["function"]["description"] == "按 id 读链接"
    # parameters 原样落库 —— 不能被 Python 侧改写
    assert schema["function"]["parameters"] == params
    assert _TOOL_SCHEMAS[-1] is schema


def test_registered_tool_is_executable_with_kwargs():
    seen = {}

    def _tool(link_id: int, tag: str = "") -> str:
        seen["link_id"] = link_id
        seen["tag"] = tag
        return "done"

    register_external(
        name="add_tag_to_link",
        description="加标签",
        parameters={
            "type": "object",
            "properties": {
                "link_id": {"type": "number"},
                "tag": {"type": "string"},
            },
            "required": ["link_id"],
        },
        fn=_tool,
    )

    runner = ToolRunner()
    result = runner.execute(
        {
            "id": "call_1",
            "type": "function",
            "function": {
                "name": "add_tag_to_link",
                "arguments": '{"link_id": 42, "tag": "小红书"}',
            },
        }
    )

    assert result["role"] == "tool"
    assert result["content"] == "done"
    assert seen == {"link_id": 42, "tag": "小红书"}


def test_guard_blocks_registered_tool_before_execution():
    """guard 检查点对外部注册的工具同样生效(Android 写确认门依赖这一点)。"""
    called = []

    register_external(
        name="set_link_remark",
        description="改备注",
        parameters={"type": "object", "properties": {}, "required": []},
        fn=lambda **kw: called.append(kw) or "done",
    )

    runner = ToolRunner()
    runner.guard = lambda name, args: "用户拒绝" if name == "set_link_remark" else None

    result = runner.execute(
        {
            "id": "call_2",
            "type": "function",
            "function": {"name": "set_link_remark", "arguments": "{}"},
        }
    )

    assert "用户拒绝" in result["content"]
    assert called == []  # 工具没被执行

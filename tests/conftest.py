"""共享 pytest fixture。

`reset_plan_mode` autouse fixture 在每个测试前后重置 `plan_mode` 模块级单例，
避免测试间状态污染（plan_mode._status / _plan_id / _plan_path / _plans_dir）。
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def reset_plan_mode(tmp_path):
    """每个测试前后重置 plan_mode 单例，plans_dir 指向临时目录。"""
    from plan_mode import plan_mode
    plan_mode._status = plan_mode.STATUS_IDLE
    plan_mode._plan_id = None
    plan_mode._plan_path = None
    plan_mode._plans_dir = tmp_path
    yield
    plan_mode._status = plan_mode.STATUS_IDLE
    plan_mode._plan_id = None
    plan_mode._plan_path = None

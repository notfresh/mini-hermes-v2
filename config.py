#!/usr/bin/env python3
"""
config.py — 配置文件加载模块
=============================

支持三级配置（优先级从高到低）：
1. 命令行参数（最高）
2. 项目配置（当前目录 .minimal-agent-v2.toml）
3. 全局配置 (~/.minimal-agent-v2/config.toml)
4. 代码默认值（最低）
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Optional


# 默认配置
DEFAULT_CONFIG: dict[str, Any] = {
    "model": "deepseek-chat",
    "provider": "deepseek",
    "max_turns": 10,
    "verbose": False,
    "skills_dir": "",
    "api": {
        "base_url": "https://api.deepseek.com/v1",
    },
}


def get_config_dir() -> Path:
    """获取全局配置目录 ~/.minimal-agent-v2/"""
    return Path("~/.minimal-agent-v2").expanduser()


def _load_toml(path: Path) -> dict[str, Any]:
    """加载 TOML 文件，返回字典"""
    if not path.exists():
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def _merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """深度合并配置，override 优先"""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _merge_config(result[key], value)
        else:
            result[key] = value
    return result


def load_config(
    config_path: Optional[Path] = None,
    project_config: Optional[Path] = None,
) -> dict[str, Any]:
    """加载配置

    Args:
        config_path: 指定配置文件路径（最高优先级）
        project_config: 项目配置文件路径（默认当前目录）

    Returns:
        合并后的配置字典
    """
    # 1. 从默认值开始
    config = DEFAULT_CONFIG.copy()

    # 2. 加载全局配置 ~/.minimal-agent-v2/config.toml
    global_config_path = get_config_dir() / "config.toml"
    config = _merge_config(config, _load_toml(global_config_path))

    # 3. 加载项目配置（当前目录 .minimal-agent-v2.toml）
    if project_config is None:
        project_config = Path(".minimal-agent-v2.toml")
    config = _merge_config(config, _load_toml(project_config))

    # 4. 命令行指定的配置文件（最高优先级）
    if config_path is not None:
        config = _merge_config(config, _load_toml(config_path))

    return config


def get_config_value(config: dict[str, Any], key: str, default: Any = None) -> Any:
    """获取配置值，支持点号访问嵌套值

    Args:
        config: 配置字典
        key: 键名，支持 "api.base_url" 形式
        default: 默认值

    Example:
        get_config_value(config, "api.base_url")
    """
    keys = key.split(".")
    value = config
    for k in keys:
        if isinstance(value, dict):
            value = value.get(k)
            if value is None:
                return default
        else:
            return default
    return value


if __name__ == "__main__":
    # 测试
    import json
    cfg = load_config()
    print(json.dumps(cfg, indent=2, ensure_ascii=False))

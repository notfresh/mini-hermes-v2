# 配置文件设计决策

## 1. 格式选择：TOML vs YAML

| | TOML | YAML |
|---|---|---|
| 依赖 | Python 3.11+ 内置 `tomllib` | 需安装 `pyyaml` |
| 语法 | 缩进不敏感 | 依赖缩进 |
| 类型 | 明确 | 需推断 |

**决策**：TOML

理由：Python 3.11+ 原生支持，无额外依赖。

## 2. 配置位置

**决策**：`~/.minimal-agent-v2/config.toml`

理由：
- 与 `session_manager.py` 已有目录 `~/.minimal-agent-v2/` 一致
- 便于后续扩展（如 `~/.minimal-agent-v2/sessions/`）
- 对比 Git 单文件（`~/.gitconfig`），Agent 工具需要存会话数据

## 3. 优先级

```
命令行参数 > 项目配置 > 全局配置 > 代码默认值
```

查找顺序：
1. 命令行 `--config` 指定路径
2. 当前目录 `./.minimal-agent-v2.toml`（项目级）
3. `~/.minimal-agent-v2/config.toml`（用户级）
4. 代码硬编码默认值

## 4. 配置项

```toml
# ~/.minimal-agent-v2/config.toml 示例
model = "deepseek-chat"
provider = "deepseek"
max_turns = 150
verbose = false
skills_dir = ""

[api]
base_url = "https://api.deepseek.com/v1"
```

## 5. 已实现

- [x] `config.py` 模块：加载配置
- [x] `cli.py` 集成配置读取
- [x] 支持 `--config` 参数覆盖默认路径

## 6. 使用方法

```bash
# 创建全局配置
mkdir -p ~/.minimal-agent-v2
cat > ~/.minimal-agent-v2/config.toml << 'EOF'
model = "deepseek-chat"
provider = "deepseek"
max_turns = 150
verbose = false

[api]
base_url = "https://api.deepseek.com/v1"
EOF

# 创建项目配置（可选，覆盖全局）
echo 'max_turns = 200' > .minimal-agent-v2.toml

# 运行
python cli.py -i
# 或指定配置文件
python cli.py -i --config /path/to/config.toml
```

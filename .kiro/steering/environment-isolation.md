# 环境隔离规范

本项目各子组件使用独立的 uv 虚拟环境，禁止在项目根目录或系统环境中直接安装依赖或运行脚本。

## mineru_mvp 组件

- 虚拟环境路径：`mineru_mvp/.venv`
- 运行任何 mineru 相关脚本前，必须使用该 venv 的 Python 解释器：`mineru_mvp/.venv/bin/python`
- 安装依赖：`cd mineru_mvp && uv sync`
- 添加依赖：`uv add <package>`；移除依赖：`uv remove <package>`
- 依赖声明在 `pyproject.toml`（不使用 requirements.txt）
- 运行脚本：`uv run python <script.py>`（自动使用 .venv）
- 禁止在项目根环境中 `pip install` mineru 的依赖

## graphrag_pipeline 组件（Agentic RAG）

- 虚拟环境路径：`graphrag_pipeline/.venv`
- 启动：`cd /path/to/graphragAgent && uv run --project graphrag_pipeline python -m graphrag_pipeline.cli`（cwd 保持项目根，让包导入正常）
- 同步依赖：`cd graphrag_pipeline && uv sync`
- 数据来源：`.env` 中 `KG_JSON_PATH` 默认指向 `../langextract_src/examples/mineru_to_kg/output/knowledge_graph.json`
- 跨阶段：与 mineru_mvp / langextract_src 完全隔离，只通过文件 IO 读取 KG

## langextract 组件（含 MVP 测试）

- 虚拟环境路径：`langextract_src/.venv`（langextract 自身与 MVP 测试共用同一 venv）
- 运行 MVP / 测试前，必须使用该 venv：
  - MVP：`cd langextract_src && uv run python examples/qwen_mvp/pipeline.py`
  - 测试：`cd langextract_src && uv run pytest tests/`
- 同步依赖：`cd langextract_src && uv sync --all-extras`
- 添加依赖：`uv add <package>`；移除依赖：`uv remove <package>`
- **MVP / 实验代码统一放到 `langextract_src/examples/<name>/`** 下（与 Google 自带的 `ollama/`、`custom_provider_plugin/` 同级），不单独建外层 venv
- 禁止在项目根环境中 `pip install` langextract 的依赖

## 通用规则

- 每个组件有自己的 `.venv/`，互不干扰
- 使用 `uv` 管理虚拟环境和依赖
- **依赖声明统一使用 `pyproject.toml`，不使用 `requirements.txt`**
- 依赖管理命令：`uv add` 添加、`uv remove` 移除、`uv sync` 同步安装
- 运行脚本：`uv run python <script.py>`（自动使用 .venv 解释器）
- 不使用 `uv pip` 或 `pip`
- `.venv/` 目录已在各组件 `.gitignore` 中忽略

## Index Pipeline 强制规则（GraphRAG 索引阶段）

Index Pipeline 跨两个独立 venv 协同（mineru_mvp + langextract），完整规范见 `docs/index_pipeline_specification-v1.0.md`。

- **两阶段必须在各自的子虚拟环境中独立运行**：
  - 阶段 1（MinerU 解析）：`cd mineru_mvp && uv run python mineru_pipeline.py`
  - 阶段 2（Bridge 抽取 + 建图）：`cd langextract_src && uv run python -m examples.mineru_to_kg.pipeline`
- 跨阶段数据传递只通过**文件系统 IO**（mineru_mvp/output → 阶段 2 默认读取 ../mineru_mvp/output）
- 禁止在 mineru_mvp/.venv 中跑 LangExtract，反之亦然
- 启动前必须 `cd` 到对应组件目录，让 uv 通过 `pyproject.toml` 自动定位 venv
- API Key（MinerU Token、Qwen Key）必须通过各组件的 `.env`，不硬编码、不提交

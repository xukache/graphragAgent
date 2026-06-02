# AGENTS.md — 项目运行规范

---

## 项目结构

```
graphragAgent/
├── frontend/              # 前端所有代码（HTML / CSS / JS）
├── backend/               # 后端服务（FastAPI）
│   ├── .env               # 外部配置（API Key 等），禁止提交 git
│   ├── .gitignore         # 必须忽略 .env / .venv/ / data/
│   ├── pyproject.toml
│   └── .venv/             # uv 独立虚拟环境
├── mineru_mvp/            # MinerU 文档解析组件
├── langextract_src/       # LangExtract 抽取 + KG 构建
├── graphrag_pipeline/     # Agentic RAG 问答（LangChain + LangGraph）
└── docs/                  # 规范文档
```

---

## 通用规则

1. **禁止在项目根目录 `pip install`**，所有依赖进对应组件的 `.venv`
2. 使用 `uv` 管理虚拟环境：`uv venv --python 3.11` / `uv sync` / `uv add` / `uv remove`
3. 依赖声明用 `pyproject.toml`，不用 `requirements.txt`，不用 `uv pip` 或 `pip`
4. 所有 API Key 等敏感配置写入 `.env`，通过 `python-dotenv` 加载，**禁止硬编码**
5. `.env` / `.venv/` / `output/` / `data/` 必须在 `.gitignore` 中，禁止提交 git
6. 跨组件数据传递只通过**文件 IO**，不跨 venv import

---

## 后端（backend/）

```bash
cd backend
uv venv --python 3.11    # 创建独立 venv
uv sync                  # 安装依赖
uv run uvicorn app.main:app --port 8000   # 启动服务
```

- 与 `graphrag_pipeline` 共享 venv（通过 `[tool.uv.sources]` 引入）
- MinerU / LangExtract 通过 **subprocess** 调用各自 venv，不直接 import
- 完整规范见 `docs/graphrag_backend_specification-v1.0.md`

---

## 前端（frontend/）

```bash
# 纯静态文件，由后端 FastAPI StaticFiles 挂载
# 无构建工具，无框架，HTML + CSS + vanilla JS + D3.js（CDN）
```

- 完整规范见 `docs/frontend_design_specification-v1.0.md`

---

## 组件：mineru_mvp

```bash
cd mineru_mvp
uv run python mineru_pipeline.py         # 解析 PDF
uv run python mineru_pipeline.py /path/to/file.pdf
```

- 独立 venv：`mineru_mvp/.venv`
- 配置：`mineru_mvp/.env`（MinerU API Token）
- 规范：`docs/mineru_specification-v1.0.md`

---

## 组件：langextract_src

```bash
cd langextract_src
uv sync --all-extras
uv run python examples/qwen_mvp/pipeline.py              # LangExtract MVP
uv run python -m examples.mineru_to_kg.pipeline           # Index Pipeline 阶段 2
```

- 独立 venv：`langextract_src/.venv`
- 配置：`langextract_src/examples/qwen_mvp/.env`（Qwen API Key）
- MVP / 实验代码放 `examples/<name>/`，共用同一 venv
- 规范：`docs/langextract_specification-v1.0.md`

---

## 组件：graphrag_pipeline

```bash
# 必须在项目根目录用 --project 锁定 venv
cd /path/to/graphragAgent
uv run --project graphrag_pipeline python -m graphrag_pipeline.cli
uv run --project graphrag_pipeline python -m graphrag_pipeline.cli -q "问题"
uv run --project graphrag_pipeline python -m graphrag_pipeline.cli --interactive
```

- 独立 venv：`graphrag_pipeline/.venv`
- 配置：`graphrag_pipeline/.env`（Qwen Key + KG_JSON_PATH）
- 规范：`docs/agentic_rag_mvp_specification-v1.0.md`

---

## Index Pipeline（索引阶段）

跨两个 venv 协同：MinerU 解析 → LangExtract 抽取 → KG 构建。

```bash
# 阶段 1：MinerU（mineru_mvp/.venv）
cd mineru_mvp && uv run python mineru_pipeline.py

# 阶段 2：LangExtract + KG（langextract_src/.venv）
cd langextract_src && uv run python -m examples.mineru_to_kg.pipeline
```

- 阶段 1 输出 → `mineru_mvp/output/`
- 阶段 2 读取 → `../mineru_mvp/output/`（文件 IO）
- 阶段 2 输出 → `langextract_src/examples/mineru_to_kg/output/`
- 规范：`docs/index_pipeline_specification-v1.0.md`

---

## 禁止操作速查

- ❌ 在 `mineru_mvp/.venv` 中跑 LangExtract
- ❌ 在 `langextract_src/.venv` 中跑 MinerU
- ❌ 在 `graphrag_pipeline/.venv` 中跑索引阶段
- ❌ 不 `cd` 到组件目录就直接 `uv run`
- ❌ 硬编码 API Key
- ❌ 提交 `.env` / `.venv/` / `output/` / `data/` 到 git

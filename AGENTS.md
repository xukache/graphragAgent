# AGENTS.md — 项目组件运行规范

本文件定义各子组件的环境隔离要求。Agent 在操作任何子组件前，必须遵循对应的虚拟环境切换规则。

---

## 组件：mineru_mvp

**路径**：`mineru_mvp/`

**虚拟环境**：`mineru_mvp/.venv`（由 `uv` 创建，Python 3.11）

**规则**：凡涉及 mineru 组件的任何操作（运行脚本、安装依赖、调试），**必须先激活该子虚拟环境**，禁止在项目根环境或系统环境中直接运行。

### 激活方式

推荐使用 `uv run`（自动使用 `.venv` 解释器，无须手动 activate）：

```bash
cd mineru_mvp
uv run python mineru_pipeline.py
```

也可以手动 activate：

```bash
# fish shell
source mineru_mvp/.venv/bin/activate.fish

# bash/zsh
source mineru_mvp/.venv/bin/activate
```

或直接使用 venv 内的 Python 解释器：

```bash
mineru_mvp/.venv/bin/python mineru_mvp/mineru_pipeline.py
```

### 依赖管理

```bash
# 同步依赖（在 mineru_mvp/ 目录下，根据 pyproject.toml 安装/更新所有依赖）
cd mineru_mvp
uv sync

# 添加新依赖
uv add <package>           # 自动更新 pyproject.toml 和 lockfile
uv add 'requests>=2.31.0'  # 带版本约束

# 移除依赖
uv remove <package>

# 运行脚本（自动使用 .venv 内解释器）
uv run python mineru_pipeline.py
```

> 使用 `pyproject.toml` 而非 `requirements.txt`。uv 项目统一用 `uv add` / `uv remove` / `uv sync` 管理依赖，不使用 `uv pip` 或 `pip`。

### 为什么隔离

- 避免 mineru 的依赖（`requests`、`reportlab` 等）与 langextract、graphrag 等组件的依赖版本冲突。
- 各组件独立演进，互不污染。
- langextract 自身与 MVP 测试共用 `langextract_src/.venv`（避免重复安装）；mineru 等业务无关组件保持独立 venv。

---

## 组件：graphrag_pipeline（Agentic RAG）

**路径**：`graphrag_pipeline/`

**虚拟环境**：`graphrag_pipeline/.venv`（由 `uv` 创建，Python 3.11）

**职责**：基于 Index Pipeline 输出的 `knowledge_graph.json`，用 LangChain + LangGraph 实现 Agentic RAG 问答链路。

**规则**：凡涉及 graphrag_pipeline 的任何操作（运行 agent、安装依赖、调试），**必须先进入该子虚拟环境**。

### 启动方式

```bash
# 推荐：在项目根用 --project 锁定 venv，cwd 保持根目录让包导入正常工作
cd /path/to/graphragAgent
uv run --project graphrag_pipeline python -m graphrag_pipeline.cli                        # 跑测试集
uv run --project graphrag_pipeline python -m graphrag_pipeline.cli -q "你的问题"          # 单问题
uv run --project graphrag_pipeline python -m graphrag_pipeline.cli --interactive           # 交互
```

### 依赖管理

```bash
cd graphrag_pipeline
uv sync               # 同步所有依赖
uv add <package>      # 添加新依赖
uv remove <package>   # 移除
```

### 数据来源

`.env` 中通过 `KG_JSON_PATH` 指向 Index Pipeline 的 KG 输出：

```bash
KG_JSON_PATH=../langextract_src/examples/mineru_to_kg/output/knowledge_graph.json
```

跨阶段数据传递与其他组件一致：**只通过文件 IO**，不跨 venv import。

---

## 组件：langextract（含 MVP 测试）

**路径**：`langextract_src/`（含本地 langextract 源码 + `examples/qwen_mvp/` MVP 测试）

**虚拟环境**：`langextract_src/.venv`（由 `uv` 创建，Python 3.11）

**规则**：凡涉及 langextract 组件的任何操作（运行 MVP、跑 pytest、调试），**必须先进入该子虚拟环境**，禁止在项目根环境或系统环境中直接运行。MVP 测试代码与 langextract 自身共用同一个 venv（避免冗余安装）。

### 激活方式

推荐使用 `uv run`（自动使用 `.venv` 解释器，无须手动 activate）：

```bash
cd langextract_src
uv run python examples/qwen_mvp/pipeline.py     # 运行 Qwen MVP
uv run pytest tests/                            # 跑 langextract 测试
```

也可以手动 activate：

```bash
# fish shell
source langextract_src/.venv/bin/activate.fish

# bash/zsh
source langextract_src/.venv/bin/activate
```

### 依赖管理

```bash
cd langextract_src

# 同步所有依赖（含 openai + test extras）
uv sync --all-extras

# 添加新依赖
uv add <package>

# 移除依赖
uv remove <package>
```

### 已安装的 extras

- `all`：OpenAI provider（`openai>=1.50.0`）
- `test`：pytest 等测试工具
- 核心依赖：`google-genai`、`pandas`、`numpy`、`pydantic`、`requests` 等

### 内置 providers

| Provider | 类 | 外部依赖 |
| --- | --- | --- |
| Gemini | `GeminiLanguageModel` | `google-genai`（核心依赖，已安装） |
| OpenAI | `OpenAILanguageModel` | `openai`（`[all]` extra，已安装） |
| Ollama | `OllamaLanguageModel` | 无额外依赖（HTTP 调用本地 Ollama 服务） |

### MVP 子目录约定

业务 / 实验 / MVP 测试代码统一放到 `langextract_src/examples/<name>/` 下（与 Google 已有的 `ollama/`、`custom_provider_plugin/` 同级），不再单独建外层 venv。每个子目录可以有自己的 `.env`、`README.md`、`output/`，但**共用 `langextract_src/.venv`**。

当前已有：

- `examples/qwen_mvp/` — 阿里千问（DashScope OpenAI-compatible）MVP 测试

---

## 通用规则

1. **禁止在项目根目录直接 `pip install`**。所有依赖安装必须进入对应组件的 `.venv`。
2. 每个组件的 `.venv/` 已在各自 `.gitignore` 中忽略，不提交到 git。
3. Agent 执行任务时，若涉及多个组件，需在切换组件时切换对应的虚拟环境。
4. 使用 `uv` 管理虚拟环境和依赖安装（速度快、确定性强）。
5. **依赖声明统一使用 `pyproject.toml`，不使用 `requirements.txt`**。使用 `uv add` 添加依赖、`uv remove` 移除依赖、`uv sync` 同步安装。不使用 `uv pip` 或 `pip`。

---

## Index Pipeline（GraphRAG 索引阶段）

**Index Pipeline 是跨两个独立虚拟环境协同的复合工作流**：原始文档 → MinerU 解析 → LangExtract 抽取 → 知识图谱原料。完整规范见 `docs/index_pipeline_specification-v1.0.md`。

### 两阶段对应的虚拟环境

| 阶段 | 组件 | 虚拟环境 | 入口脚本 |
| --- | --- | --- | --- |
| 阶段 1：解析 | mineru_mvp | `mineru_mvp/.venv` | `mineru_pipeline.py` |
| 阶段 2：抽取 + 建图 | mineru_to_kg | `langextract_src/.venv` | `examples/mineru_to_kg/pipeline.py` |

### 启动规则（强制）

**Index Pipeline 的两个阶段必须在各自的子虚拟环境中独立运行**，禁止在同一 venv 中跑两个阶段。

**阶段 1：MinerU 解析**

```bash
cd mineru_mvp                            # ← 必须先 cd 到组件目录
uv run python mineru_pipeline.py
```

**阶段 2：Bridge 抽取 + 建图**

```bash
cd langextract_src                       # ← 必须 cd 到 langextract_src（不是 examples/mineru_to_kg）
uv run python -m examples.mineru_to_kg.pipeline
```

### 跨阶段数据传递

- 唯一通道：**文件系统 IO**（不通过进程间通信、共享内存或跨 venv import）
- 阶段 1 输出：`mineru_mvp/output/{uuid}_content_list.json` + `task_meta.json` + `images/`
- 阶段 2 默认读取：`../mineru_mvp/output/`（可通过 `--mineru-output` 覆盖）

### Index Pipeline 不允许的操作

- ❌ 在 `mineru_mvp/.venv` 中跑 LangExtract 抽取（缺 langextract）
- ❌ 在 `langextract_src/.venv` 中跑 MinerU API 调用（缺 reportlab）
- ❌ 不 `cd` 到组件目录就直接 `uv run`
- ❌ 在脚本里硬编码 MinerU Token 或 Qwen API Key（必须通过各自的 `.env`）
- ❌ 把 `mineru_mvp/output/` 与 `examples/mineru_to_kg/output/` 提交到 git

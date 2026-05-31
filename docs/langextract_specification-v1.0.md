# LangExtract Pipeline 规范 v1.0（实测校准版）

本规范以 **本项目实际跑通的 LangExtract MVP（Qwen via OpenAI-compatible 端点）输出为准**，并对照本地源码 `langextract_src/` 与 `docs/langextract_pipeline_spec.md` 校准。

> 校准原则：**凡本地实际行为与文档描述冲突，一律以本地实际输出为准**，并以「⚠️ 实测校准」标注差异。

实测环境信息：

| 项 | 实测值 | 来源 |
| --- | --- | --- |
| LangExtract 版本 | 1.5.0 | `langextract_src/pyproject.toml` |
| Python | 3.11 | `langextract_src/.venv` |
| 模型后端 | 阿里千问 DashScope（OpenAI-compatible） | `examples/qwen_mvp/.env` |
| 实际请求模型 | `qwen3.7-max`（DashScope 别名容错，实际生效） | 运行日志 |
| 输入文本 | 中文医学/科研文本，242 字符（单段） | `examples/qwen_mvp/pipeline.py` |
| 输出抽取条数 | **15 条**，覆盖 8 个 `extraction_class` | `extraction_results.jsonl` |
| 对齐结果 | `match_exact` × 4，`match_fuzzy` × 1，`None` × 10 | 实测分布 |

本文档结构：

1. 完整 pipeline 执行思路 + 实测脚本存放位置
2. 实际输出文件清单
3. 各文件实际字段规范（实测为准）
4. Pipeline 关键参数规范
5. 运行环境与虚拟环境约束
6. 信息来源

---

## 1. 完整 Pipeline 执行思路与脚本位置

### 1.1 脚本存放位置

LangExtract 相关的所有 MVP / 实验代码统一放在 `langextract_src/examples/` 下（与 Google 自带的 `ollama/`、`custom_provider_plugin/` 同级），**复用 `langextract_src/.venv`**，不另建外层组件。

当前目录结构：

```
langextract_src/
├── .venv/                     # 唯一的 langextract 虚拟环境
├── pyproject.toml             # langextract 自身依赖（含 [all] / [test] extras）
├── langextract/               # langextract 源码包
└── examples/
    ├── ollama/                   # Google 自带
    ├── custom_provider_plugin/   # Google 自带
    └── qwen_mvp/                 # 本项目 MVP
        ├── .env                  # Qwen 配置（含 Key，已 gitignore）
        ├── .gitignore
        ├── pipeline.py           # 主 pipeline 脚本
        ├── README.md
        └── output/               # 抽取结果（运行后生成）
```

| 文件 | 作用 |
| --- | --- |
| `examples/qwen_mvp/.env` | `QWEN_API_KEY` / `QWEN_API_BASE` / `QWEN_LLM_MODEL` 等配置 |
| `examples/qwen_mvp/pipeline.py` | **主 pipeline**：构造模型配置 → 调用 `lx.extract()` → 落盘 |
| `examples/qwen_mvp/README.md` | 使用说明 |
| `examples/qwen_mvp/output/` | 三类落盘产物（详见第 2 节） |

### 1.2 执行思路（文本输入 → LLM 抽取 → 结构化结果落盘）

LangExtract 是**纯文本结构化抽取组件**，本身不解析 PDF / 图片 / 音视频，因此 pipeline 起点必须是已经处理好的文本。完整链路：

```text
[1] 准备纯文本输入
       text: str  或  Iterable[lx.data.Document]
       （多模态文档需先经 MinerU 等解析层转为文本）
        │
        ▼
[2] 准备 prompt + examples
       prompt_description: str           （任务描述）
       examples: Sequence[ExampleData]   （≥1 个，硬约束）
        │
        ▼
[3] 构造模型配置（OpenAI-compatible 端点接 Qwen）
       ModelConfig(
           model_id="qwen3.7-max",
           provider="OpenAILanguageModel",   # 显式指定，绕过 model_id 自动路由
           provider_kwargs={
               "api_key": ..., "base_url": ...,
               "format_type": FormatType.JSON,
               "temperature": 0.0,
           }
       )
        │
        ▼
[4] 调用 lx.extract()
       use_schema_constraints=False   # 第三方端点 schema 兼容性差，关闭更稳
       fence_output=True              # 模型输出用 ```json``` 包裹，解析更稳
        │
        内部流程：tokenize -> ChunkIterator -> prompt 拼接 -> LLM 推理
                 -> Resolver 解析 JSON -> 对齐回原文（char/token interval）
        │
        ▼
[5] 输出
       AnnotatedDocument
        │
        ▼
[6] 落盘（三类产物，详见第 2 节）
       extraction_results.jsonl  （标准 LangExtract JSONL）
       extractions_raw.json      （扁平明细，人类阅读）
       visualization.html        （HTML 高亮可视化）
```

### 1.3 实测踩坑与对策（已固化进 `pipeline.py`）

| 现象 | 根因 | 对策 |
| --- | --- | --- |
| `ImportError: Using SOCKS proxy, but the 'socksio' package is not installed` | 本机 `ALL_PROXY=socks5://...` 把国内 DashScope 也代理走了 | `pipeline.py` 启动时主动 `os.environ.pop` 掉所有 `*_PROXY` 变量 |
| `model_id="qwen3.7-max"` 直接传报"找不到 provider" | LangExtract 的 `factory.create_model()` 用 model_id 模式匹配 provider，千问 model_id 不在内置匹配表中 | 用 `ModelConfig(provider="OpenAILanguageModel", provider_kwargs={...})` **显式指定 provider** + `base_url` + `api_key` |
| OpenAI structured output schema 报错 | DashScope 兼容端点对 OpenAI structured outputs 支持不完整 | `use_schema_constraints=False` |
| 模型偶尔输出非 JSON 文本 | 第三方端点 JSON 模式不稳定 | `fence_output=True` 让模型用 ` ```json ``` ` 包裹，Resolver 解析更稳 |
| 抽取出的 `extraction_text` 与原文不完全一致 | LLM 会精炼/缩写（如把"王明远教授"输出为"王明远"） | 这是正常现象，体现在 `alignment_status=None`；本规范第 3 节有处理建议 |

### 1.4 实测运行结果（成功）

```text
[1/4] 准备输入文本（242 字符）
[2/4] 构造模型配置（OpenAI-compatible 接入 Qwen）
[3/4] lx.extract() 调用，~21s 完成
[4/4] 抽取条数: 15  已对齐到原文: 5/15
      按类别：cohort:1 / disease:2 / drug:2 / duration:1 / metric:3 / organization:3 / person:2 / publication:1
Pipeline 执行完成 ✅
```

数值精确还原（**312 / 10 mg / 12 个月 / 2.4 分 / 0.8 分 / p<0.01 / 2024 年第 23 卷第 5 期**），attributes 丰富填充了角色、所属机构、给药方式、统计学含义等业务字段。

---

## 2. 实际输出文件清单（实测为准）

`pipeline.py` 在 `output/` 下生成 **3 个文件**：

| 实际文件名 | 大小 | 类别 | 用途 |
| --- | --- | --- | --- |
| `extraction_results.jsonl` | 5113 B | 标准产物 | LangExtract 标准 JSONL，含 `char_interval`、`alignment_status`，可用 `lx.io.load_annotated_documents_jsonl()` 反序列化 |
| `extractions_raw.json` | 4365 B | 扁平产物 | 人类阅读友好，扁平化的抽取明细数组 |
| `visualization.html` | 16662 B | 可视化产物 | LangExtract 生成的 HTML 高亮页面（带 hover tooltip） |

⚠️ 实测校准：

- 文档原本提到 `lx.io.save_annotated_documents()` 输出 JSONL；实测**它直接把单文档保存为单行 JSONL**（5113 字节、1 行），即 `AnnotatedDocument` 的 JSON 序列化。
- 文档提到 `lx.visualize()` 在 Jupyter 中返回 `IPython.display.HTML`；实测**非 Jupyter 环境直接返回 HTML 字符串**，pipeline 中按 `isinstance(html, str)` 判断后落盘。

---

## 3. 各文件实际字段规范（实测为准）

### 3.1 `extraction_results.jsonl`（标准 LangExtract JSONL）

实测顶层字段（**单行 JSON 即一个 `AnnotatedDocument`**）：

| 字段 | 实测类型 | 实测值/示例 |
| --- | --- | --- |
| `extractions` | list[dict] | 15 个元素 |
| `text` | string | 原始输入文本（实测 242 字符，与输入完全一致） |
| `document_id` | string | `doc_10053e04`（自动生成，未显式传入时随机短 ID） |

⚠️ 实测校准：

- 文档列出的 `tokenized_text` 字段在 JSONL 中**不存在**。源码定义中它是延迟生成的，序列化时被排除。对接代码不要假设此字段存在。
- 顶层只有 3 个字段：`extractions` / `text` / `document_id`。

### 3.2 单条 `extraction` 实测结构

实测每个抽取条目的字段：

| 字段 | 实测类型 | 实测说明 |
| --- | --- | --- |
| `extraction_class` | string | 抽取类别（实测 8 类：person/organization/disease/drug/metric/cohort/duration/publication） |
| `extraction_text` | string | 抽取出的文本内容（可能与原文不完全一致） |
| `char_interval` | dict / null | `{"start_pos": int, "end_pos": int}` 或 `null` |
| `alignment_status` | string / null | 实测取值：`"match_exact"` / `"match_fuzzy"` / `null`（未对齐） |
| `extraction_index` | int | 抽取顺序索引（实测从 1 开始） |
| `group_index` | int | 模型输出中的分组索引（实测从 0 开始） |
| `description` | null | 实测全部为 `null`（默认行为） |
| `attributes` | dict / null | 字符串键值对，由模型生成，含业务字段 |

实测真实条目（带对齐）：

```json
{
  "extraction_class": "metric",
  "extraction_text": "实验组的 MMSE 评分平均提升 2.4 分",
  "char_interval": {"start_pos": 126, "end_pos": 148},
  "alignment_status": "match_exact",
  "extraction_index": 10,
  "group_index": 9,
  "description": null,
  "attributes": {
    "metric_type": "疗效",
    "metric_name": "MMSE 评分",
    "value": "2.4",
    "unit": "分",
    "direction": "提升",
    "group": "实验组"
  }
}
```

实测真实条目（未对齐）：

```json
{
  "extraction_class": "person",
  "extraction_text": "王明远",
  "char_interval": null,
  "alignment_status": null,
  "extraction_index": 1,
  "group_index": 0,
  "description": null,
  "attributes": {"role": "神经内科主任", "title": "教授"}
}
```

### 3.3 `alignment_status` 实测分布与处理建议

实测 15 条抽取的对齐分布：

| `alignment_status` | 数量 | 说明 |
| --- | --- | --- |
| `null`（未对齐） | 10 | 模型输出 `extraction_text` 与原文有差异（如简写"王明远教授"→"王明远"） |
| `match_exact` | 4 | 完全 token 级匹配，含 `char_interval` |
| `match_fuzzy` | 1 | fuzzy 匹配，含 `char_interval` |

⚠️ 实测校准：**未对齐占比偏高（10/15）属正常现象**，因为 LLM 倾向于精炼输出（去掉头衔、单位、修饰词）。文档第 3.5 节列出的 `match_greater` / `match_lesser` 状态在本次未触发。

下游接入建议（基于实测）：

- **结构化抽取**（实体/关系入库、JSON 字段）：直接使用所有抽取，不要因 `alignment_status=null` 丢弃，否则会丢失 67% 的结果。
- **原文高亮 / 证据回溯**：仅使用 `char_interval != null` 的条目（实测 5/15）。
- **批量校验**：可后处理通过子串/规则匹配补对齐，提高对齐率。

### 3.4 `extractions_raw.json`（扁平产物，人类阅读友好）

由 `pipeline.py` 自定义生成，结构是扁平数组：

```json
[
  {
    "extraction_class": "metric",
    "extraction_text": "实验组的 MMSE 评分平均提升 2.4 分",
    "attributes": {...},
    "char_interval": {"start_pos": 126, "end_pos": 148},
    "alignment_status": "match_exact"
  },
  ...
]
```

字段是 JSONL 中字段的子集（不含 `extraction_index` / `group_index` / `description` / `text` / `document_id`）。仅用于快速人工审阅。

### 3.5 `visualization.html`（HTML 可视化）

实测特征：

- **完整可独立打开的 HTML 片段**（不是完整 HTML 文档，无 `<html>`/`<body>`，但浏览器可直接渲染）
- 使用 `lx.lx-highlight` 等 CSS 类，文本中按 `char_interval` 对应的位置着色高亮
- 每个高亮片段含 `lx-tooltip`，悬停可见 `extraction_class` 与 `attributes`
- **只有 `char_interval != null` 的抽取参与高亮**（实测 5/15）

下游集成时，可直接 `<iframe srcdoc>` 嵌入或拼接到自有页面。

---

## 4. Pipeline 关键参数规范

### 4.1 鉴权与连接参数（必须）

| 参数（.env 键） | 实测值 | 说明 |
| --- | --- | --- |
| `QWEN_API_KEY` | `sk-...` | 阿里 DashScope API Key |
| `QWEN_API_BASE` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | OpenAI-compatible 端点 |
| `QWEN_LLM_MODEL` | `qwen3.7-max` | 模型 ID。DashScope 实测对 `qwen3.7-max` / `qwen3-max` / `qwen-max` / `qwen-plus` / `qwen-turbo` 均可调通 |

预留但本 MVP 未启用：`QWEN_VL_MODEL`、`EMBEDDING_MODEL`、`VL_EMBEDDING_MODEL`。

### 4.2 `lx.extract()` 关键参数（实测稳定组合）

| 参数 | 实测值 | 作用 | 调整建议 |
| --- | --- | --- | --- |
| `text_or_documents` | `str` 或 `Iterable[Document]` | 输入文本（必填） | 多文档批处理传 list；单段文本传 str |
| `prompt_description` | str | 任务描述 | 越具体抽取越准；建议列出每个 `extraction_class` 的语义 |
| `examples` | `Sequence[ExampleData]` | 示例（**≥1 个，硬约束**） | 示例越贴近真实场景效果越好；attributes 字段也作示范用 |
| `config` | `ModelConfig` | 模型配置 | OpenAI-compatible 端点用此参数（不要用 `model_id` 顶层参数） |
| `use_schema_constraints` | **`False`**（实测必须） | 是否用 provider schema 约束模型输出 | 第三方 OpenAI-compatible 端点统一关闭；Gemini 原生时可开启 |
| `fence_output` | **`True`**（实测推荐） | 是否要求模型用 ```` ```json ```` 包裹 | 第三方端点开启更稳；Gemini structured 模式可关 |

### 4.3 `ModelConfig.provider_kwargs` 实测稳定组合

| 字段 | 实测值 | 说明 |
| --- | --- | --- |
| `api_key` | `.env` 中的 `QWEN_API_KEY` | 必填 |
| `base_url` | `.env` 中的 `QWEN_API_BASE` | OpenAI-compatible 端点必填 |
| `format_type` | `lx.data.FormatType.JSON` | 推荐显式指定，避免 YAML 路径 |
| `temperature` | `0.0` | 抽取任务建议 0，稳定可复现 |
| `max_workers` | `4` | 并发请求数（多 chunk 时生效） |

### 4.4 关键参数与场景适配

| 场景 | 推荐组合 |
| --- | --- |
| 第三方 OpenAI-compatible 端点（Qwen / DeepSeek / 智谱 / Moonshot） | `provider="OpenAILanguageModel"` + `base_url` + `use_schema_constraints=False` + `fence_output=True` |
| Gemini 官方 | `model_id="gemini-1.5-flash"`（自动路由）+ 默认 schema 约束 |
| OpenAI 官方 | `model_id="gpt-4o-mini"`（自动路由）+ structured outputs 可启用 |
| Ollama 本地 | `model_id="gemma2:2b"` + `model_url="http://localhost:11434"` |

### 4.5 输入与示例（实测约束）

- `examples` **必须 ≥1**，否则 `extract()` 抛错
- 示例的 `extraction_text` 应当是 `text` 内的原文片段，否则 LangExtract 会打 prompt alignment WARNING（实测多条 `Prompt alignment: FAILED to align` 日志，**不影响调用成功**，但会降低对齐率）
- `prompt_description` 越细致，模型生成的 `attributes` 越规范

### 4.6 输出落盘（实测稳定 API）

```python
# 标准 JSONL
lx.io.save_annotated_documents(
    [result],
    output_name="extraction_results.jsonl",
    output_dir=str(OUTPUT_DIR),
)

# HTML 可视化
html = lx.visualize(str(jsonl_path))
html_str = html if isinstance(html, str) else getattr(html, "data", str(html))
Path("visualization.html").write_text(html_str, encoding="utf-8")
```

---

## 5. 运行环境与虚拟环境约束（必读）

LangExtract 组件**必须在 `langextract_src/.venv` 中运行**，不允许在项目根环境或系统 Python 中直接运行 MVP 脚本或安装依赖。

### 5.1 启动路径（推荐）

```bash
# 进入 langextract_src 目录（虚拟环境隔离的入口）
cd langextract_src

# 用 uv run 自动使用 .venv 解释器（无须手动 activate）
uv run python examples/qwen_mvp/pipeline.py

# 或先 activate
source .venv/bin/activate.fish    # fish
# source .venv/bin/activate       # bash/zsh
python examples/qwen_mvp/pipeline.py
```

### 5.2 依赖管理

```bash
cd langextract_src
uv sync --all-extras       # 同步所有依赖（含 [all]=openai 与 [test]=pytest）
uv add <package>           # 添加新依赖到 pyproject.toml
uv remove <package>        # 移除
```

### 5.3 MVP / 实验代码约定

- **统一放到 `langextract_src/examples/<name>/`** 下，与 Google 自带 `ollama/`、`custom_provider_plugin/` 同级
- 每个子目录可有自己的 `.env`、`README.md`、`output/`，**共用 `langextract_src/.venv`**
- 不再为 MVP 单独建外层目录或第二个 venv

### 5.4 不允许的操作

- ❌ 在项目根目录或系统 Python 中 `pip install langextract`
- ❌ 在 `langextract_src/` 之外建第二个 langextract venv
- ❌ 在 MVP 脚本里硬编码 API Key（必须通过 `.env`）
- ❌ 提交 `.env` / `.venv/` / `output/` 到 git（已在 `.gitignore`）

详细规则参见项目根目录 `AGENTS.md` 的 **「组件：langextract（含 MVP 测试）」** 节，以及 `.kiro/steering/environment-isolation.md` 的同名节。

---

## 6. 信息来源

- 本地源码：`langextract_src/langextract/`（v1.5.0）
- 现有规范：`docs/langextract_pipeline_spec.md`
- 实测脚本与输出：`langextract_src/examples/qwen_mvp/`
- 千问 OpenAI-compatible 端点：阿里 DashScope（兼容模式）

> 凡本规范「⚠️ 实测校准」处，均以本地实际输出为准。后续接入新 provider（Gemini / DeepSeek / 本地 Ollama 等）时，应在 `examples/<name>/` 下补充实测，并据此继续校准本规范。

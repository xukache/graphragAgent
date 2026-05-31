# GraphRAG 索引阶段 Index Pipeline 规范 v1.0（实测校准版）

本规范以 **本项目实际跑通的 MinerU + LangExtract Index Pipeline 输出为准**，定义从「原始 PDF → MinerU 解析 → LangExtract 抽取 → 知识图谱原料」的完整索引链路，作为 GraphRAG 索引阶段的核心流程。

> 校准原则：**凡本地实际行为与文档描述冲突，一律以本地实际输出为准**，并以「⚠️ 实测校准」标注差异。

**前置规范**：
- `docs/mineru_specification-v1.0.md`（MinerU 实测输出规范）
- `docs/langextract_specification-v1.0.md`（LangExtract 实测输入输出规范）
- `docs/mineru2langextract_handoff-v1.0.md`（对接规划）

**实测环境信息**：

| 项 | 实测值 | 来源 |
| --- | --- | --- |
| MinerU 后端 | `_backend=hybrid`，`_version_name=3.1.8` | `mineru_mvp/output/layout.json` |
| LangExtract 版本 | 1.5.0 | `langextract_src/pyproject.toml` |
| LLM | 阿里千问 `qwen3.7-max`（OpenAI-compatible） | `examples/qwen_mvp/.env` |
| 测试输入 | `mineru_mvp/sample.pdf`（1 页，含中文标题/正文/4 列 5 行数值表格/公式行） | 本地生成 |
| 实测产出 | 17 实体 / 34 三元组（重试 1 次后稳定） | `examples/mineru_to_kg/output/` |

**本规范结构**：

1. 完整 Index Pipeline 执行思路 + 测试脚本位置
2. MinerU 与 LangExtract 接口对接规范
3. MinerU 关键参数规范
4. LangExtract 关键参数规范
5. Index Pipeline 最终输出的关键参数规范
6. 虚拟环境与运行约束
7. 信息来源

---

## 1. 完整 Index Pipeline 执行思路与脚本位置

### 1.1 脚本存放位置

Index Pipeline 跨**两个独立虚拟环境**协同：

| 阶段 | 虚拟环境 | 脚本目录 | 入口脚本 |
| --- | --- | --- | --- |
| MinerU 解析 | `mineru_mvp/.venv` | `mineru_mvp/` | `mineru_pipeline.py` |
| LangExtract 抽取 + KG 构建 | `langextract_src/.venv` | `langextract_src/examples/mineru_to_kg/` | `pipeline.py` |

**完整文件清单**：

```
mineru_mvp/
├── .env                           # MinerU API Token（gitignore）
├── .gitignore
├── pyproject.toml                 # uv 依赖
├── make_sample_pdf.py             # 生成测试 PDF
├── mineru_pipeline.py             # 阶段 1：上传 → 轮询 → 下载 → 解压
├── README.md
├── sample.pdf                     # 测试 PDF
├── .venv/                         # 独立 venv
└── output/                        # MinerU 解析产物（→ Bridge 输入）

langextract_src/
├── .venv/                         # 独立 venv
└── examples/
    ├── __init__.py
    ├── qwen_mvp/                  # 独立 LangExtract MVP（参考）
    │   └── .env                   # Qwen API Key（被 mineru_to_kg 复用）
    └── mineru_to_kg/              # 阶段 2：Bridge 主组件
        ├── __init__.py
        ├── .gitignore
        ├── README.md
        ├── table_parser.py        # MinerU table_body HTML → Markdown
        ├── converter.py           # content_list.json → list[Document]
        ├── prompts.py             # 9 类 extraction_class 的 PROMPT + examples
        ├── kg_builder.py          # 实体归一化 + 三元组 + JSON/Cypher/Markdown 导出
        ├── pipeline.py            # 阶段 2 端到端主脚本
        └── output/                # KG 索引产物（→ GraphRAG 输入）
```

### 1.2 Index Pipeline 完整链路

```text
[输入] 原始 PDF / Word / PPT / Excel / 图片 / HTML
   │
   ▼  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ┃ 阶段 1：MinerU 解析（mineru_mvp/.venv）
   ┃ ─────────────────────────────────────
   ┃ [1.1] 申请上传链接  POST /api/v4/file-urls/batch
   ┃ [1.2] PUT 上传文件到 OSS
   ┃ [1.3] 轮询任务结果  GET /api/v4/extract-results/batch/{batch_id}
   ┃        state: waiting-file → pending → running → done
   ┃ [1.4] 下载 + 解压 full_zip_url（带代理回退重试）
   ┃ [1.5] 落盘 mineru_mvp/output/
   ▼  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
mineru_mvp/output/
   ├── {uuid}_content_list.json   ★ Bridge 主入口（阅读顺序 + 0-1000 bbox）
   ├── full.md                    （备用兜底，纯 Markdown）
   ├── layout.json                （精确像素坐标，按需）
   ├── images/                    （图表截图，本阶段仅记录路径）
   └── task_meta.json             （batch_id / file_name / data_id）
   │
   ▼  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ┃ 阶段 2：Bridge 抽取 + 建图（langextract_src/.venv）
   ┃ ─────────────────────────────────────
   ┃ [2.1] load_content_list()    glob *content_list.json，读取块列表
   ┃ [2.2] content_list_to_documents()
   ┃        - 按 page_idx 分组（策略 B）
   ┃        - text 块直接拼接，标题加 `## ` 分段
   ┃        - table 块 → table_html_to_markdown() Markdown 表格
   ┃        - equation 块保留 LaTeX
   ┃        - additional_context 携带 source_file/page_idx/blocks 元数据
   ┃ [2.3] lx.extract()  Qwen via OpenAI-compatible
   ┃        - ModelConfig(provider="OpenAILanguageModel")
   ┃        - use_schema_constraints=False, fence_output=True
   ┃        - 失败重试最多 3 次（LLM 偶尔返回空 JSON）
   ┃ [2.4] 落盘抽取结果（JSONL + 扁平 JSON + HTML 可视化）
   ┃ [2.5] build_knowledge_graph()
   ┃        - normalize_entities() 实体归一化
   ┃        - generate_triples() 三类来源生成三元组
   ┃        - export_json/cypher/markdown 多格式导出
   ▼  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[输出] examples/mineru_to_kg/output/
   ├── extraction_results.jsonl   （LangExtract 标准 JSONL）
   ├── extractions_raw.json       （扁平抽取明细）
   ├── visualization.html         （HTML 高亮）
   ├── knowledge_graph.json       ★ GraphRAG 输入（节点 + 三元组）
   ├── knowledge_graph.cypher     （Neo4j 导入脚本）
   └── knowledge_graph.md         （人工审阅摘要）
```

### 1.3 启动方式（实测可复现）

**阶段 1：MinerU 解析（在 `mineru_mvp/.venv` 内）**

```bash
cd mineru_mvp
uv sync                                  # 同步依赖到 .venv（首次）
uv run python make_sample_pdf.py         # 生成测试 PDF
uv run python mineru_pipeline.py         # 解析 → mineru_mvp/output/
# 或指定其他本地 PDF
uv run python mineru_pipeline.py /path/to/your.pdf
```

**阶段 2：Bridge 抽取 + 建图（在 `langextract_src/.venv` 内）**

```bash
cd langextract_src
uv sync --all-extras                     # 同步依赖（含 [all]=openai 与 [test]=pytest）
# 默认读取 ../mineru_mvp/output
uv run python -m examples.mineru_to_kg.pipeline
# 或指定其他 mineru 输出目录
uv run python -m examples.mineru_to_kg.pipeline \
    --mineru-output /path/to/mineru/output \
    --output-dir /path/to/save
```

⚠️ 两个阶段必须在**各自独立的虚拟环境**中运行。详见第 6 节。

### 1.4 实测踩坑与对策（已固化进脚本）

| 现象 | 阶段 | 对策 |
| --- | --- | --- |
| `401 A0202 user authenticate failed` | MinerU | Token 末尾误粘多余字符；`.env` 存放干净 Token（HS512 签名 86 字符） |
| 下载结果 `SSL: UNEXPECTED_EOF_WHILE_READING` | MinerU | 国内 CDN 经代理失败；`_download_zip()` 自动绕过代理直连重试 |
| `ImportError: Using SOCKS proxy, but the 'socksio' package is not installed` | LangExtract | DashScope 是国内域名；`pipeline.py` 启动时 `os.environ.pop` 所有 `*_PROXY` |
| `model_id="qwen3.7-max"` 报"找不到 provider" | LangExtract | 千问不在内置匹配表；用 `ModelConfig(provider="OpenAILanguageModel", provider_kwargs={...})` 显式指定 |
| 抽取偶尔返回 0 条 | LangExtract | 第三方端点 JSON 模式不稳定；pipeline 实现重试 3 次（实测第 2 次成功率高） |
| 中文渲染成 ■ | MinerU 测试输入 | 源 PDF 字体无 CJK 字形；reportlab 注册 CID 字体 `STSong-Light` |

### 1.5 实测运行结果

```text
[阶段 1] MinerU
  状态流转：waiting-file → pending → running → done
  解压 7 个条目；content_list.json 块类型统计：table:1 / text:9

[阶段 2] Bridge
  [1/5] 加载块数 10，生成 1 个 Document（594 字符）
  [2/5] examples 1 个（含 12 个示范 extraction）
  [3/5] 抽取完成（第 2/3 次尝试）：17 条 extraction
  [4/5] JSONL / 扁平 JSON / HTML 落盘
  [5/5] 实体节点 17，三元组 34
        按类别：organization:1 / duration:1 / metric:15
        按谓词：has_value:15 / has_营业收入/净利润/毛利率 各 5 / org_type:1 / duration_*:3
```

**数值精度 100%**：表格 4 列 × 5 行 = 15 个数值全部入图，每个都正确归属到 Q1/Q2/Q3/Q4/全年 分组，单位 unit 字段精确（百万元人民币 / %）。

---

## 2. MinerU 与 LangExtract 接口对接规范

### 2.1 对接边界与契约

```
MinerU 输出层（mineru_mvp/output/）
    │  契约：{uuid}_content_list.json + task_meta.json + images/
    ▼
Bridge 转换层（converter.py + table_parser.py）
    │  契约：list[lx.data.Document]
    ▼
LangExtract 抽取层（lx.extract() via Qwen）
    │  契约：list[AnnotatedDocument]
    ▼
KG 构建层（kg_builder.py）
    │  契约：knowledge_graph.json
    ▼
下游 GraphRAG 索引
```

### 2.2 第一道接口：MinerU output → Bridge 转换层

**输入契约（实测为准）**：

| 文件 | 必需 | 说明 |
| --- | --- | --- |
| `*content_list.json`（不带 v2 后缀） | 必需 | 主入口，按阅读顺序排列的扁平块列表 |
| `task_meta.json` | 可选 | 用于读取 `file_name`；缺失时从 uuid 前缀推断 |
| `images/` | 可选 | 图表截图目录；本阶段仅引用 `img_path`，不做二次识别 |
| `*content_list_v2.json` | **不使用** | 结构开发版，本 Bridge 不消费 |
| `layout.json` | **不使用** | 精确像素坐标，仅供下游裁剪/对位（按需） |
| `*model.json` | **不使用** | 模型推理原始输出，本 Bridge 不消费 |

**实测块类型与转换规则**：

| MinerU 块类型 | 实测出现 | 转换策略 | 进入 Document.text |
| --- | --- | --- | --- |
| `text`（无 text_level） | ✅ | 取 `text` 字段 | ✅ 原样 |
| `text`（text_level ≥ 1） | ✅ | 前加 `##` / `###` 作标题分段 | ✅ |
| `table` | ✅ | `table_body` HTML → Markdown 表格（含 caption / footnote） | ✅ 转换后文本 |
| `equation` | 未触发 | 取 `text`（LaTeX） | ✅ 保留 `$$...$$` |
| `image` / `chart` | 未触发 | 取 `image_caption` + `image_footnote` | ✅（如有 caption） |
| `code` | 未触发 | 取 `code_body` 包 ```` ``` ```` | ✅ |
| `list` | 未触发 | `list_items` 拼接为 `- xxx` | ✅ |
| `header` / `footer` / `page_number` / `aside_text` / `page_footnote` | 未触发 | **跳过** | ❌ |

**转换工具**：

```python
from examples.mineru_to_kg.converter import (
    load_content_list,           # (mineru_dir) -> (blocks, source_file)
    content_list_to_documents,   # (blocks, source_file) -> list[Document]
)
from examples.mineru_to_kg.table_parser import table_html_to_markdown
```

### 2.3 第二道接口：Bridge 转换层 → LangExtract

**输出契约（实测为准）**：每页生成一个 `lx.data.Document`：

```python
lx.data.Document(
    text=str,                # 该页所有块拼接后的纯文本（用 \n\n 分隔）
    document_id=str,         # 实测："{source_file}_page_{page_idx}"
    additional_context=str,  # JSON 字符串：{source_file, page_idx, blocks: [...]}
)
```

`additional_context` 实测结构（每个块保留 `type` / `bbox`(0-1000) / 可选 `text_level`、`img_path`、`sub_type`）：

```json
{
  "source_file": "sample.pdf",
  "page_idx": 0,
  "blocks": [
    {"type": "text", "bbox": [317, 74, 678, 99], "text_level": 1},
    {"type": "table", "bbox": [161, 306, 835, 439], "img_path": "images/2675...jpg"}
  ]
}
```

### 2.4 第三道接口：LangExtract → KG 构建层

**输入契约（来自 LangExtract，实测稳定）**：

```python
AnnotatedDocument(
    document_id: str,
    text: str,
    extractions: list[Extraction],
)

Extraction(
    extraction_class: str,            # 9 类：person/organization/disease/drug/metric/cohort/duration/publication/relationship
    extraction_text: str,
    char_interval: dict | None,       # {"start_pos": int, "end_pos": int}
    alignment_status: str | None,     # "match_exact" / "match_fuzzy" / "match_lesser" / null
    extraction_index: int,
    group_index: int,
    description: null,
    attributes: dict | None,
)
```

**`extraction_class` 与 attributes 体系（本 Bridge 定义，由 prompts.py 强约束）**：

| extraction_class | attributes 字段 |
| --- | --- |
| `person` | `role`, `title`, `affiliation` |
| `organization` | `type`, `department`, `parent` |
| `disease` | `category` |
| `drug` | `dosage`, `unit`, `frequency`, `indication`, `group` |
| `metric` | `metric_type`, `metric_name`, `value`, `unit`, `direction`, `group` |
| `cohort` | `size`, `unit`, `age_criteria`, `condition` |
| `duration` | `value`, `unit`, `type` |
| `publication` | `type`, `journal_name`, `year`, `volume`, `issue` |
| `relationship` | `head`, `tail`, `relation_type` |

### 2.5 三套坐标系（关键，避免数值错位）

实测同一标题块在三个 MinerU 文件中的坐标：

| 文件 | bbox 示例 | 坐标系 | Bridge 是否使用 |
| --- | --- | --- | --- |
| `*content_list.json` | `[317, 74, 678, 99]` | 0-1000 归一化整数 | ✅ 存入 additional_context |
| `*model.json` | `[0.319, 0.075, 0.68, 0.1]` | [0,1] 归一化浮点 | ❌ |
| `layout.json` | `[189, 63, 404, 84]`（配 page_size [595,841]） | 原始页面像素 | ❌ |

**Bridge 仅使用 0-1000 坐标**。下游若需精确像素位置，应单独读取 `layout.json` 并自行换算。

### 2.6 实体归一化与三元组生成规则

**实体签名（`_entity_signature`）**：

| extraction_class | 签名规则 |
| --- | --- |
| `metric` | `metric_name + value + group + unit` 唯一（每个数值是独立实体） |
| `person` | `label + affiliation`（同名同所属合并） |
| 其他 | `class + 归一化 label` |

**entity_id 生成**：`f"e_{sha1(signature)[:8]}"`，实测均为 8 位 hex（如 `e_42d809dd`）。

**三元组三类来源（`generate_triples`）**：

| 来源 | 谓词模式 | 示例 |
| --- | --- | --- |
| `relationship` 类抽取 | `attributes.relation_type` | `(张伟, 任职于, 北京协和医院)` |
| `metric` 类 | `(group_label, has_<metric_name>, {value, unit})` 与 `(metric_id, has_value, {value, unit})` | `(_group_Q1, has_营业收入, {value:1280.50, unit:百万元人民币})` |
| 其他类 attributes | `ATTR_TO_PREDICATE` 映射 | `(person_id, affiliated_with, org_id)`、`(org_id, org_type, {value:医院})` |

`ATTR_TO_PREDICATE` 映射表（kg_builder.py 内）覆盖：
- person.affiliation → `affiliated_with`
- person.role → `has_role`
- organization.parent → `sub_org_of`
- drug.indication → `indicates`
- publication.journal_name → `published_in`
- duration.value → `duration_value`
- 等共 16 条规则

---

## 3. MinerU 关键参数规范

参数集中在 `mineru_mvp/.env`，由 `MineruConfig.from_env()` 读取。

### 3.1 鉴权与连接（必须）

| 参数（.env 键） | 实测值 | 说明 |
| --- | --- | --- |
| `MINERU_API_TOKEN` | （必填，HS512 签名 86 字符） | Bearer Token |
| `MINERU_API_BASE` | `https://mineru.net/api/v4` | API 基址，固定 v4（v2/v3 已停服） |

请求头（脚本固定，必须）：`Content-Type: application/json` + `Authorization: Bearer <token>`（**Bearer 后必须有空格**）。

### 3.2 解析行为（可灵活调整）

| 参数（.env 键） | 默认 | 实测值 | API 字段 | 调整建议 |
| --- | --- | --- | --- | --- |
| `MINERU_MODEL_VERSION` | `vlm` | `vlm`（实际后端落 `hybrid`） | `model_version` | HTML 文件必须 `MinerU-HTML`；非 HTML 推荐 `vlm` |
| `MINERU_LANGUAGE` | `ch` | `ch` | `language` | 影响 OCR；仅 pipeline/vlm 有效 |
| `MINERU_ENABLE_TABLE` | `true` | `true` | `enable_table` | 数值密集文档务必保持 `true` |
| `MINERU_ENABLE_FORMULA` | `true` | `true` | `enable_formula` | vlm 下仅影响行内公式 |
| `MINERU_IS_OCR` | `false` | `false` | `file.is_ocr` | 扫描件/图片需置 `true` |

⚠️ 实测：请求 `model_version=vlm` 但结果 `_backend=hybrid`。**对接时以输出文件实际结构为准**，不假设后端等于请求值。

### 3.3 轮询与下载（工程鲁棒性）

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `MINERU_POLL_INTERVAL` | `5`（秒） | 轮询间隔 |
| `MINERU_POLL_TIMEOUT` | `600`（秒） | 总超时；200 页大文档应上调 |
| 下载重试（脚本内） | `max_retries=4` | 第 1 次按系统代理；第 2 次起绕过代理直连 |

### 3.4 文件类型适配速查

| 文件类型 | model_version | is_ocr |
| --- | --- | --- |
| 普通 PDF（电子版） | `vlm` | `false` |
| 扫描件 PDF / 图片 | `vlm` 或 `pipeline` | `true` |
| HTML | `MinerU-HTML` | — |
| Word / PPT / Excel | `vlm` 或 `pipeline` | `false` |

---

## 4. LangExtract 关键参数规范

参数集中在 `langextract_src/examples/qwen_mvp/.env`（被 `mineru_to_kg` 复用）。

### 4.1 鉴权与连接（必须）

| 参数（.env 键） | 实测值 | 说明 |
| --- | --- | --- |
| `QWEN_API_KEY` | `sk-...` | DashScope API Key |
| `QWEN_API_BASE` | `https://dashscope.aliyuncs.com/compatible-mode/v1` | OpenAI-compatible 端点 |
| `QWEN_LLM_MODEL` | `qwen3.7-max` | 实测可用：`qwen3.7-max` / `qwen3-max` / `qwen-max` / `qwen-plus` / `qwen-turbo` |

### 4.2 `lx.extract()` 实测稳定组合

| 参数 | 实测值 | 调整建议 |
| --- | --- | --- |
| `text_or_documents` | `list[Document]`（按页分） | 多文档批处理传 list；单段传 str |
| `prompt_description` | 见 `prompts.py PROMPT` | 越具体抽取越准；列出每个 class 的 attributes 字段 |
| `examples` | 1 个 ExampleData，含 12 个示范 extraction | **≥1 个，硬约束**；越贴近真实场景效果越好 |
| `config` | `ModelConfig(provider="OpenAILanguageModel", ...)` | OpenAI-compatible 端点必须显式指定 provider |
| `use_schema_constraints` | **`False`** | 第三方端点必须关闭；Gemini 原生时可开启 |
| `fence_output` | **`True`** | 第三方端点必须开启，让模型用 ` ```json ``` ` 包裹 |

### 4.3 `ModelConfig.provider_kwargs` 实测稳定组合

| 字段 | 实测值 | 说明 |
| --- | --- | --- |
| `api_key` | `.env` 中的 `QWEN_API_KEY` | 必填 |
| `base_url` | `.env` 中的 `QWEN_API_BASE` | OpenAI-compatible 端点必填 |
| `format_type` | `lx.data.FormatType.JSON` | 推荐显式指定 |
| `temperature` | `0.0` | 抽取任务建议 0，稳定可复现 |
| `max_workers` | `4` | 并发请求数（多 chunk 时生效） |

### 4.4 重试机制（pipeline.py 实现）

```python
max_attempts = 3
for attempt in range(1, max_attempts + 1):
    results = lx.extract(...)
    total = sum(len(r.extractions or []) for r in results_list)
    if total > 0:
        break  # 成功
    # 重试：第三方端点偶尔返回空 JSON
```

实测：第 1 次失败、第 2 次成功的情况实际发生过，重试机制是必要的。

### 4.5 场景适配速查

| 场景 | 推荐参数 |
| --- | --- |
| 第三方 OpenAI-compatible（Qwen / DeepSeek / 智谱 / Moonshot） | `provider="OpenAILanguageModel"` + `base_url` + `use_schema_constraints=False` + `fence_output=True` |
| Gemini 官方 | `model_id="gemini-1.5-flash"`（自动路由）+ 默认 schema 约束 |
| OpenAI 官方 | `model_id="gpt-4o-mini"`（自动路由）+ structured outputs 可启用 |
| Ollama 本地 | `model_id="gemma2:2b"` + `model_url="http://localhost:11434"` |

---

## 5. Index Pipeline 最终输出规范

`langextract_src/examples/mineru_to_kg/output/` 共 **6 个文件**，按用途分三层：

### 5.1 文件清单（实测）

| 文件 | 实测大小 | 类别 | 用途 |
| --- | --- | --- | --- |
| `extraction_results.jsonl` | ~7 KB | LangExtract 标准 | 单行 JSON 即一个 AnnotatedDocument，可用 `lx.io.load_annotated_documents_jsonl()` 反序列化 |
| `extractions_raw.json` | ~7 KB | 扁平明细 | 人工审阅或后处理消费 |
| `visualization.html` | ~33 KB | HTML 高亮 | 浏览器直接打开（仅 `char_interval != null` 的 extraction 参与高亮） |
| `knowledge_graph.json` | ~20 KB | **GraphRAG 主输入** | 节点 + 三元组 + 统计 |
| `knowledge_graph.cypher` | ~4 KB | Neo4j 导入脚本 | `cypher-shell -f` 直接执行 |
| `knowledge_graph.md` | ~5 KB | 人工审阅摘要 | Markdown 报告 |

### 5.2 `knowledge_graph.json` 顶层结构（GraphRAG 索引主输入）

实测顶层字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `entities` | list[dict] | 实体节点列表 |
| `triples` | list[dict] | 三元组列表（边 + 字面量边） |
| `stats` | dict | 统计信息 |

**实测 stats 结构**：

```json
{
  "entity_count": 17,
  "triple_count": 34,
  "by_class": {"organization": 1, "duration": 1, "metric": 15},
  "by_predicate": {
    "org_type": 1, "duration_value": 1, "duration_unit": 1, "duration_type": 1,
    "has_营业收入": 5, "has_value": 15, "has_净利润": 5, "has_毛利率": 5
  }
}
```

### 5.3 `entities[i]` 结构（实测）

| 字段 | 实测类型 | 说明 |
| --- | --- | --- |
| `entity_id` | string | `e_<sha1[:8]>`，全局唯一 |
| `entity_class` | string | 9 类之一（不含 relationship） |
| `label` | string | 规范化显示名（metric 用 `metric_name（group）` 格式） |
| `aliases` | list[string] | 同义别名（如不同写法的同一实体） |
| `properties` | dict | 来自 `extraction.attributes` 的字段并集 |
| `sources` | list[dict] | 出处链：`[{document_id, char_interval, alignment_status}]` |

**实测真实条目**：

```json
{
  "entity_id": "e_42d809dd",
  "entity_class": "organization",
  "label": "MinerU",
  "aliases": [],
  "properties": {"type": "API/产品"},
  "sources": [{
    "document_id": "sample.pdf_page_0",
    "char_interval": {"start_pos": 3, "end_pos": 9},
    "alignment_status": "match_exact"
  }]
}
```

### 5.4 `triples[i]` 结构（实测）

| 字段 | 实测类型 | 说明 |
| --- | --- | --- |
| `subject` | string | entity_id 或 `_group_xxx` 虚拟节点 ID |
| `predicate` | string | 关系名（动词形式） |
| `object` | string \| dict | entity_id（图边）或 `{"value": ..., "unit": ...}`（字面量边） |
| `metadata` | dict | `{document_id, extraction_class, [warning], [group_label]}` |

**两种实测形态**：

字面量边（实测最常见）：

```json
{
  "subject": "e_42d809dd",
  "predicate": "org_type",
  "object": {"value": "API/产品"},
  "metadata": {"document_id": "sample.pdf_page_0", "extraction_class": "organization"}
}
```

metric 数值边（带分组虚拟节点）：

```json
{
  "subject": "_group_Q1",
  "predicate": "has_营业收入",
  "object": {"value": "1280.50", "unit": "百万元人民币", "metric_id": "e_2fd958c0"},
  "metadata": {"document_id": "sample.pdf_page_0", "extraction_class": "metric", "group_label": "Q1"}
}
```

实体-实体边（本次样例未触发，但 schema 已支持）：

```json
{
  "subject": "e_xxx",
  "predicate": "affiliated_with",
  "object": "e_yyy",
  "metadata": {"document_id": "...", "extraction_class": "person"}
}
```

### 5.5 `knowledge_graph.cypher` 实测格式

每个节点用 `MERGE`，标签是 `entity_class.capitalize()`：

```cypher
MERGE (n:Organization { id: 'e_42d809dd' })
SET n += {id: 'e_42d809dd', label: 'MinerU', type: 'API/产品'};

MERGE (n:Metric { id: 'e_2fd958c0' })
SET n += {
  id: 'e_2fd958c0', label: '营业收入（Q1）',
  metric_type: '财务指标', metric_name: '营业收入',
  value: '1280.50', unit: '百万元人民币', group: 'Q1',
  aliases: ['1280.50']
};
```

实体-实体关系用 `MATCH ... MERGE`：

```cypher
MATCH (a {id: 'e_xxx'}), (b {id: 'e_yyy'})
MERGE (a)-[:AFFILIATED_WITH]->(b);
```

⚠️ 字面量边（object 为 dict）目前**不写入 Cypher**（避免污染图结构），它们只存在于 `knowledge_graph.json` 中。下游入 Neo4j 时若需要字面量，可单独从 JSON 读取并作为节点属性写入。

### 5.6 GraphRAG 索引消费建议

下游 GraphRAG 系统消费 `knowledge_graph.json` 时建议的字段映射：

| GraphRAG 概念 | 映射来源 |
| --- | --- |
| 节点 ID | `entities[i].entity_id` |
| 节点标签 / 类型 | `entities[i].entity_class` |
| 节点显示名 | `entities[i].label` |
| 节点属性 | `entities[i].properties` |
| 节点别名（用于查询匹配） | `entities[i].aliases` |
| 节点出处（溯源） | `entities[i].sources[*]`（含 document_id 与 char_interval） |
| 边的头/尾 | `triples[i].subject` / `triples[i].object`（仅 string 时） |
| 边的关系 | `triples[i].predicate` |
| 边的属性 | `triples[i].metadata` |
| 字面量属性 | `triples[i].object`（dict 时），可作为节点属性挂在 subject 上 |

---

## 6. 虚拟环境与运行约束（必读）

Index Pipeline 跨**两个独立虚拟环境**协同。**任何阶段启动前必须先进入对应的子虚拟环境**，禁止在项目根环境或系统 Python 中直接运行。

### 6.1 两个 venv 的职责边界

| 组件 | venv 路径 | 职责 |
| --- | --- | --- |
| `mineru_mvp` | `mineru_mvp/.venv` | MinerU API 调用、PDF 解析、结果落盘 |
| `langextract`（含 mineru_to_kg） | `langextract_src/.venv` | LangExtract 抽取、Bridge 转换、KG 构建 |

两个 venv **完全隔离**：
- 不共享依赖（实测验证：mineru_mvp 有 reportlab 无 langextract；langextract_src 反之）
- 跨阶段通过**文件 IO**传递数据（不共享 Python 进程或对象）
- 启动入口靠 `cwd` 决定走哪个 venv（`uv run` 自动定位 `pyproject.toml`）

### 6.2 启动路径（两阶段独立切换）

**阶段 1：MinerU**

```bash
cd mineru_mvp                            # ← 必须先 cd
uv run python mineru_pipeline.py
```

**阶段 2：Bridge（LangExtract）**

```bash
cd langextract_src                       # ← 必须 cd 到这里（不是 examples/mineru_to_kg）
uv run python -m examples.mineru_to_kg.pipeline
```

### 6.3 不允许的操作

- ❌ 在项目根目录或系统 Python 中 `pip install` 任何 mineru / langextract 依赖
- ❌ 在 `mineru_mvp/.venv` 中跑 LangExtract 抽取（会缺 langextract 包）
- ❌ 在 `langextract_src/.venv` 中跑 MinerU 调用（会缺 reportlab 等）
- ❌ 不 `cd` 到组件目录就直接 `uv run`（uv 找不到 `pyproject.toml` 会报错）
- ❌ 在脚本里硬编码 API Key（必须通过 `.env`）
- ❌ 提交 `.env` / `.venv/` / `output/` 到 git（已在各组件 `.gitignore`）

### 6.4 跨阶段数据传递

**唯一通道**：通过文件系统读写（不通过进程间通信、共享内存或 import）。

```
阶段 1 写入 → mineru_mvp/output/
                      │
                      │（文件 IO）
                      ▼
阶段 2 读取 ← examples/mineru_to_kg/pipeline.py 默认 --mineru-output ../mineru_mvp/output
```

依赖管理统一约定：

```bash
# 添加新依赖（在对应组件目录下）
uv add <package>
# 移除
uv remove <package>
# 同步
uv sync                        # mineru_mvp
uv sync --all-extras           # langextract_src（含 [all]/[test]）
```

详细规则参见 `AGENTS.md` 与 `.kiro/steering/environment-isolation.md`。

---

## 7. 信息来源

- 前置规范：`docs/mineru_specification-v1.0.md`、`docs/langextract_specification-v1.0.md`、`docs/mineru2langextract_handoff-v1.0.md`
- 阶段 1 实测：`mineru_mvp/output/`（`_backend=hybrid`，`_version_name=3.1.8`）
- 阶段 2 实测：`langextract_src/examples/mineru_to_kg/output/`（17 实体 / 34 三元组，2026-05-30）
- 环境隔离规范：`AGENTS.md`、`.kiro/steering/environment-isolation.md`
- LLM 后端：阿里千问 DashScope OpenAI-compatible 兼容模式

> 凡本规范「⚠️ 实测校准」标注处，均以本地实际输出为准。后续接入新 provider 或扩展到更复杂文档（多页 / 含图表 / 多语言）时，应在 `examples/mineru_to_kg/output/` 下补充实测，并据此继续校准本规范。

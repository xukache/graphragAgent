# MinerU → LangExtract 对接规划 v1.0

本文档定义 MinerU 文档解析输出到 LangExtract 结构化抽取输入的完整对接方案，用于实现「原始 PDF → 结构化知识图谱」的端到端 pipeline。

**依据规范：**
- `docs/mineru_specification-v1.0.md`（MinerU 实测输出规范）
- `docs/langextract_specification-v1.0.md`（LangExtract 实测输入输出规范）

---

## 1. 数据流总览

```text
原始 PDF
  │
  ▼  [mineru_mvp/.venv]  mineru_pipeline.py
mineru_mvp/output/
  ├── {uuid}_content_list.json   ← 对接主入口（阅读顺序 + 0-1000 bbox）
  ├── full.md                    ← 备用兜底（纯 Markdown 文本）
  ├── layout.json                ← 精确坐标补充（原始像素，按需使用）
  └── images/                    ← 图表截图（本阶段仅记录路径，不做二次识别）
  │
  ▼  [转换层]  content_list_to_documents()
  │
  ▼  [langextract_src/.venv]  对接 pipeline 脚本
langextract_src/examples/mineru_to_kg/output/
  ├── extraction_results.jsonl   ← 标准 LangExtract JSONL
  ├── extractions_raw.json       ← 扁平明细
  └── visualization.html         ← HTML 高亮可视化
```

**环境隔离：**
- MinerU 解析在 `mineru_mvp/.venv` 中运行
- 转换 + LangExtract 抽取在 `langextract_src/.venv` 中运行
- 对接脚本放在 `langextract_src/examples/mineru_to_kg/`，跨目录读取 `mineru_mvp/output/`（读文件，不跨 venv）

---

## 2. 核心对接点：content_list.json → langextract Document

### 2.1 MinerU 输出端（实测结构）

`{uuid}_content_list.json` 是扁平数组，每个元素：

```json
{
  "type": "text",
  "text": "正文内容",
  "text_level": 1,
  "page_idx": 0,
  "bbox": [317, 74, 678, 99]
}
```

```json
{
  "type": "table",
  "table_body": "<table><tr><td>季度</td><td>营业收入</td>...</tr></table>",
  "table_caption": [],
  "table_footnote": [],
  "img_path": "images/xxx.jpg",
  "page_idx": 0,
  "bbox": [161, 306, 835, 439]
}
```

实测出现的 `type` 值：`text`、`table`。官方还支持 `equation`、`image`、`chart`、`code`、`list`、`header`/`footer`/`page_number`/`aside_text`/`page_footnote`。

### 2.2 LangExtract 输入端（实测约束）

```python
lx.data.Document(
    text: str,                     # 必填，纯文本（不接受 PDF/图片/HTML）
    document_id: str | None,       # 可选，用于溯源
    additional_context: str | None # 可选，补充到 prompt 中
)
```

硬约束：
- `text` 必须是纯文本字符串
- `examples` 必须 ≥ 1 个 `ExampleData`
- 使用 `ModelConfig` 显式指定 provider（Qwen OpenAI-compatible 端点）

### 2.3 转换规则

| content_list 块类型 | 转换策略 | 进入 Document.text | 备注 |
|---|---|---|---|
| `text`（无 text_level） | 直接取 `text` 字段 | ✅ 原样 | 正文段落 |
| `text`（text_level ≥ 1） | 取 `text`，前加 `\n\n## ` 作为分隔 | ✅ 作为 chunk 边界 | 标题，用于分段 |
| `table` | `table_body` HTML → Markdown 表格文本 | ✅ 转换后文本 | 详见第 3 节 |
| `equation` | 取 `text`（LaTeX），原样保留 `$$...$$` | ✅ 原样 | 公式 |
| `image` / `chart` | 仅取 `image_caption` + `image_footnote` 文本 | ✅（如有 caption） | 图内数值不处理 |
| `code` | 取 `code_body` 文本 | ✅ 原样 | 代码块 |
| `list` | 取 `list_items` 拼接为文本 | ✅ 逐条拼接 | 列表 |
| `header`/`footer`/`page_number`/`aside_text`/`page_footnote` | **跳过** | ❌ | 辅助块，无抽取价值 |

---

## 3. 表格转换策略

### 3.1 为什么不直接喂 HTML

- HTML 标签消耗 token 但不增加语义信息
- Markdown 表格对 LLM 更友好，结构化抽取准确率更高
- 实测 MinerU 的 `table_body` 是标准 `<table><tr><td>` 结构，可靠解析

### 3.2 转换规则

```
输入（MinerU table_body）：
<table><tr><td>季度</td><td>营业收入</td><td>净利润</td></tr>
<tr><td>Q1</td><td>1280.50</td><td>210.30</td></tr>...</table>

输出（喂给 LangExtract 的文本）：
| 季度 | 营业收入 | 净利润 |
| Q1 | 1280.50 | 210.30 |
| Q2 | 1395.75 | 248.60 |
...
```

### 3.3 实现要点

- 使用 Python 标准库 `html.parser` 解析（不引入额外依赖）
- 处理 `rowspan` / `colspan`（MinerU 实测表格含这些属性）
- 空单元格保留为空字符串，不丢弃列
- 转换失败时 fallback：直接去除 HTML 标签，保留纯文本

---

## 4. 分块策略（Document 粒度）

### 4.1 三种策略对比

| 策略 | 做法 | Document 数量 | 适用场景 |
|---|---|---|---|
| **A. 整文档单 Document** | 所有块拼成一个长文本 | 1 | 短文档（< 5000 字） |
| **B. 按页分 Document** | 每页一个 Document | = 页数 | 中等文档（5-50 页） |
| **C. 按标题分 Document** | 遇 `text_level ≥ 1` 切分 | = 章节数 | 长文档（> 50 页） |

### 4.2 MVP 推荐：策略 B（按页分 Document）

理由：
- 粒度适中，单页文本量通常在 LLM 上下文窗口内
- `document_id` 天然对应 `page_idx`，溯源清晰
- 后续可平滑升级到策略 C（按标题分）
- 与 MinerU 的 `page_idx` 字段直接对应

实现：

```python
def content_list_to_documents(
    blocks: list[dict],
    source_file: str,
) -> list[lx.data.Document]:
    """按页分组，每页生成一个 Document。"""
    pages: dict[int, list[dict]] = {}
    for block in blocks:
        page_idx = block.get("page_idx", 0)
        pages.setdefault(page_idx, []).append(block)

    documents = []
    for page_idx in sorted(pages.keys()):
        text_parts = []
        block_meta = []
        for block in pages[page_idx]:
            converted = convert_block_to_text(block)
            if converted:
                text_parts.append(converted)
                block_meta.append({
                    "type": block["type"],
                    "bbox": block.get("bbox"),
                    "text_level": block.get("text_level"),
                })

        if text_parts:
            documents.append(lx.data.Document(
                text="\n\n".join(text_parts),
                document_id=f"{source_file}_page_{page_idx}",
                additional_context=json.dumps({
                    "source_file": source_file,
                    "page_idx": page_idx,
                    "blocks": block_meta,
                }, ensure_ascii=False),
            ))
    return documents
```

---

## 5. 元数据溯源设计

### 5.1 Document 级元数据（additional_context）

```json
{
  "source_file": "sample.pdf",
  "page_idx": 0,
  "blocks": [
    {"type": "text", "bbox": [317,74,678,99], "text_level": 1},
    {"type": "table", "bbox": [161,306,835,439]},
    {"type": "text", "bbox": [97,495,847,533]}
  ]
}
```

### 5.2 抽取结果溯源链路

```text
AnnotatedDocument.document_id = "sample.pdf_page_0"
  → 定位到原文档第 0 页
  → additional_context.blocks 定位到具体块
  → char_interval 定位到块内文本位置
  → bbox（0-1000）定位到页面物理位置
```

### 5.3 坐标系说明（重要）

| 来源 | 坐标系 | 用途 |
|---|---|---|
| content_list.json `bbox` | 0-1000 归一化整数 | 块级定位，存入 additional_context |
| layout.json `bbox` | 原始页面像素（配合 page_size） | 精确裁剪/对位（按需） |
| LangExtract `char_interval` | 字符偏移（Document.text 内） | 文本级定位 |

三者不可混用。对接时只使用 content_list 的 0-1000 坐标。

---

## 6. Prompt 与 Examples 设计

### 6.1 面向知识图谱的 extraction_class 体系

| extraction_class | 语义 | 典型 attributes |
|---|---|---|
| `person` | 人物 | role, title, affiliation |
| `organization` | 机构/组织 | type, department, parent |
| `disease` | 疾病/症状 | category, icd_code |
| `drug` | 药物/治疗手段 | dosage, unit, frequency, indication |
| `metric` | 关键数值指标 | metric_type, metric_name, value, unit, direction, group |
| `cohort` | 研究队列/样本 | size, unit, age_criteria, condition |
| `duration` | 时间周期 | value, unit, type |
| `publication` | 发表/文献 | type, journal_name, year, volume, issue |
| `relationship` | 实体间关系 | head_entity, tail_entity, relation_type |

### 6.2 Prompt 模板

```python
PROMPT = (
    "从文档中抽取以下结构化信息，用于构建知识图谱。"
    "每个抽取项的 extraction_text 尽量使用原文片段。"
    "抽取类别包括："
    "(1) person 人物（含角色、头衔、所属机构）；"
    "(2) organization 机构（含类型、上级机构）；"
    "(3) disease 疾病/症状；"
    "(4) drug 药物（含剂量、频次、适应症）；"
    "(5) metric 关键数值指标（含指标名、值、单位、方向、分组）；"
    "(6) cohort 研究队列（含样本量、纳入标准）；"
    "(7) duration 时间周期；"
    "(8) publication 发表文献（含期刊、年份、卷期）；"
    "(9) relationship 实体间关系（含头实体、尾实体、关系类型）。"
    "不要遗漏数值与单位。attributes 中尽量补充可解析的结构化字段。"
)
```

### 6.3 Examples 设计原则

- 至少 1 个 ExampleData（硬约束）
- 示例文本应覆盖：正文实体 + 表格数值 + 实体间关系
- `extraction_text` 必须是示例 `text` 中的原文片段（提高对齐率）
- attributes 字段做充分示范（模型会模仿示例的 attributes 结构）

---

## 7. LangExtract 调用参数（实测稳定组合）

```python
from langextract.factory import ModelConfig

config = ModelConfig(
    model_id=os.environ["QWEN_LLM_MODEL"],
    provider="OpenAILanguageModel",
    provider_kwargs={
        "api_key": os.environ["QWEN_API_KEY"],
        "base_url": os.environ["QWEN_API_BASE"],
        "format_type": lx.data.FormatType.JSON,
        "temperature": 0.0,
        "max_workers": 4,
    },
)

results = lx.extract(
    text_or_documents=documents,       # list[Document]，按页分
    prompt_description=PROMPT,
    examples=examples,
    config=config,
    use_schema_constraints=False,      # 第三方端点必须关闭
    fence_output=True,                 # 第三方端点推荐开启
)
```

---

## 8. 输出与后处理

### 8.1 直接产物

| 文件 | 内容 | 用途 |
|---|---|---|
| `extraction_results.jsonl` | 标准 LangExtract JSONL（含 char_interval、alignment_status） | 下游入库 |
| `extractions_raw.json` | 扁平明细 | 人工审阅 |
| `visualization.html` | HTML 高亮 | 可视化验证 |

### 8.2 面向知识图谱的后处理（本规划定义，实现在后续迭代）

```text
extraction_results.jsonl
  → 过滤：丢弃 extraction_class 不在预定义体系中的条目
  → 实体归一化：相同实体不同表述合并（如"华山医院" = "复旦大学附属华山医院"）
  → 关系建模：从 relationship 类抽取构建三元组 (head, relation, tail)
  → 去重：基于 extraction_text + attributes 的相似度去重
  → 输出：知识图谱三元组（JSON / Neo4j 导入格式 / NetworkX 图）
```

本 v1.0 规划聚焦于**对接层**（MinerU → LangExtract），后处理层在后续版本规划。

---

## 9. 目录结构与文件规划

```
langextract_src/examples/mineru_to_kg/
├── .env                    # 复用 qwen_mvp 的配置（或 symlink）
├── .gitignore              # 忽略 output/、.env
├── README.md
├── pipeline.py             # 端到端 pipeline（读取 mineru output → 转换 → 抽取 → 落盘）
├── converter.py            # content_list → Document 转换逻辑
├── table_parser.py         # table_body HTML → Markdown 文本
├── prompts.py              # prompt + examples 定义
└── output/                 # 抽取结果
```

运行方式：

```bash
cd langextract_src
uv run python examples/mineru_to_kg/pipeline.py
# 或指定 mineru 输出目录
uv run python examples/mineru_to_kg/pipeline.py --mineru-output ../mineru_mvp/output
```

---

## 10. 实现步骤（建议顺序）

| 步骤 | 内容 | 验证标准 |
|---|---|---|
| 1 | 编写 `table_parser.py`：HTML → Markdown 表格 | 用 mineru_mvp/output 的真实 table_body 验证转换正确 |
| 2 | 编写 `converter.py`：content_list → list[Document] | 验证按页分组、text 拼接、additional_context 完整 |
| 3 | 编写 `prompts.py`：prompt + examples | 覆盖 text/table/relationship 场景 |
| 4 | 编写 `pipeline.py`：端到端串联 | 读取真实 mineru output → 转换 → lx.extract() → 落盘 |
| 5 | 用 `mineru_mvp/output/` 真实数据跑通 | 15+ 条抽取，数值精确，表格数据完整 |
| 6 | 评估对齐率与抽取质量 | 基于 alignment_status 分布和人工抽检 |

---

## 11. 已知风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 表格 HTML 含 rowspan/colspan | 转 Markdown 时行列错位 | table_parser 处理合并单元格；失败时 fallback 去标签 |
| 长文档单页文本超出 LLM 上下文 | 抽取不完整 | 按页分 Document 已缓解；极端情况可进一步按标题切分 |
| 跨页实体重复出现 | 知识图谱中产生重复节点 | 后处理阶段做实体归一化（基于 text + attributes 匹配） |
| alignment_status=null 占比高（实测 67%） | 无法做原文高亮 | 结构化抽取不依赖对齐；高亮功能降级为"仅展示可对齐的" |
| 图表中的数值无法通过文本抽取 | 遗漏图内数据 | 本阶段标记 img_path 到 additional_context，不阻塞主流程；后续可接 VL 模型 |
| 代理环境导致 DashScope 连接失败 | pipeline 报错 | 脚本启动时清理 *_PROXY 环境变量（已在 qwen_mvp 中验证） |
| MinerU 输出文件名含 UUID 前缀 | 硬编码路径会失败 | 用 glob 匹配 `*content_list.json`，不假设文件名 |

---

## 12. 配置复用

对接脚本复用 `qwen_mvp/.env` 的配置（或创建 symlink）：

```bash
# .env 内容（与 qwen_mvp 相同）
QWEN_API_KEY=sk-...
QWEN_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_LLM_MODEL=qwen3.7-max
```

无须额外配置。MinerU 的 Token 不在此处使用（MinerU 解析已在 mineru_mvp 中完成）。

---

## 13. 成功标准（MVP 验收）

| 维度 | 标准 |
|---|---|
| 端到端跑通 | 从 `mineru_mvp/output/` 读取 → 转换 → 抽取 → 落盘，无报错 |
| 数值精确 | 表格中的数值（1280.50、210.30 等）在抽取结果中完整出现 |
| 实体覆盖 | 至少覆盖 person、organization、metric、table 数值 4 类 |
| 溯源可用 | document_id 可回溯到页码，additional_context 含块级 bbox |
| 环境隔离 | 全程在 `langextract_src/.venv` 中运行，不污染其他组件 |

---

## 14. 信息来源

- MinerU 输出规范：`docs/mineru_specification-v1.0.md`
- LangExtract 输入输出规范：`docs/langextract_specification-v1.0.md`
- MinerU 实测数据：`mineru_mvp/output/`
- LangExtract 实测数据：`langextract_src/examples/qwen_mvp/output/`
- 环境隔离规范：`AGENTS.md` + `.kiro/steering/environment-isolation.md`

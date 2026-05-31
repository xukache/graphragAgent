# MinerU → LangExtract 知识图谱抽取

基于 `docs/mineru2langextract_handoff-v1.0.md`，实现「MinerU 解析输出 → LangExtract 结构化抽取 → 知识图谱原料」的端到端 pipeline。

## 完整链路

```
mineru_mvp/output/
   ├── {uuid}_content_list.json   # 主入口
   ├── full.md
   └── images/
        │
        ▼  [content_list_to_documents]
list[Document]（按页分组，table → Markdown）
        │
        ▼  [lx.extract() via Qwen]
AnnotatedDocument
        │
        ▼  [落盘]
output/
   ├── extraction_results.jsonl
   ├── extractions_raw.json
   └── visualization.html
```

## 文件

```
examples/mineru_to_kg/
├── .gitignore
├── __init__.py
├── README.md
├── converter.py        # content_list → list[Document]
├── table_parser.py     # table_body HTML → Markdown 表格
├── prompts.py          # PROMPT + examples
├── kg_builder.py       # 实体归一化 + 三元组生成 + 多格式导出
├── pipeline.py         # 端到端主脚本（5 步：加载→构造→抽取→落盘→建图）
└── output/             # 抽取结果（运行后生成）
```

## 运行

```bash
cd langextract_src

# 默认读取 ../mineru_mvp/output
uv run python -m examples.mineru_to_kg.pipeline

# 指定其他 mineru 输出目录
uv run python -m examples.mineru_to_kg.pipeline \
    --mineru-output /path/to/mineru/output \
    --output-dir /path/to/save/results
```

## 配置

复用 `langextract_src/examples/qwen_mvp/.env`（Qwen DashScope OpenAI-compatible 端点）。

如需独立配置，在本目录下创建 `.env`：

```bash
QWEN_API_KEY=sk-...
QWEN_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_LLM_MODEL=qwen3.7-max
```

## 实测结果（2026-05-30）

输入：`mineru_mvp/output/sample.pdf` 解析产物（10 个块，1 页，含 1 个 4×5 数值表格）

```
[1/4] 加载块数: 10，生成 1 个 Document（594 字符）
[3/4] 抽取完成：17 条 extraction
[4/4] 类别分布：metric:15  organization:1  duration:1
       对齐分布：match_exact:16  match_lesser:1
```

**数值精确还原：** 表格中 5×3=15 个数值全部抽取，每个都带正确的指标名（营业收入/净利润/毛利率）、单位（百万元人民币/%）、分组（Q1/Q2/Q3/Q4/全年）。

## 关键设计决策

1. **按页分 Document（策略 B）**：`document_id = "{source}_page_{page_idx}"`，溯源清晰。
2. **表格转 Markdown 而非保留 HTML**：实测对 LLM 更友好，数值抽取准确率显著提升。
3. **元数据通过 `additional_context` 传递**：含 source_file / page_idx / blocks（type+bbox+text_level），供下游溯源使用。
4. **表格中每个数值单独抽取为 metric**：在 examples 中明确示范，并通过 prompt 强调"表格中的每一个数值都要单独抽取"。
5. **代理清理 + provider 显式指定**：复用 qwen_mvp 的踩坑经验。

## 输出说明

- **`extraction_results.jsonl`**：标准 LangExtract JSONL（每行一个 AnnotatedDocument），可用 `lx.io.load_annotated_documents_jsonl()` 反序列化。
- **`extractions_raw.json`**：扁平化的抽取明细（含 document_id），供人工审阅或后处理脚本消费。
- **`visualization.html`**：HTML 高亮可视化（仅 `char_interval != null` 的抽取参与高亮）。
- **`knowledge_graph.json`**：知识图谱节点 + 三元组（含统计），可被 NetworkX / 自定义图引擎消费。
- **`knowledge_graph.cypher`**：Neo4j 导入脚本（`MERGE` 节点 + 关系），可直接 `cypher-shell -f` 执行。
- **`knowledge_graph.md`**：人类阅读友好的 KG 摘要报告。

## 后处理设计（已实现）

`kg_builder.py` 在抽取完成后自动构建知识图谱：

1. **实体归一化**（`normalize_entities`）：相同实体不同表述合并为同一 `entity_id`（基于 `extraction_class + label + 关键 attrs` 签名）。`metric` 类按 `metric_name + value + group + unit` 唯一化，每个数值是独立节点。
2. **三元组生成**（`generate_triples`）：
   - **显式**：`relationship` 类抽取 → `(head_id, relation_type, tail_id)`
   - **数值**：`metric` 类 → `(group_label, has_<metric_name>, {value, unit})`
   - **隐式**：从 attributes 推导（如 `person.affiliation` → `affiliated_with` 边）
3. **多格式导出**：JSON 三元组（程序消费）/ Cypher（Neo4j 导入）/ Markdown（人工审阅）。

无外部图库依赖，下游可自行 load 到 NetworkX、Neo4j 或自定义图存储。

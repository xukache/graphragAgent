# GraphRAG Pipeline (Agentic RAG MVP)

基于 LangChain + LangGraph 的 Agentic RAG 实现，问答数据源是 Index Pipeline 输出的 `knowledge_graph.json`。

**链路：** 用户问题 → LangGraph Agent → 选择 KG 检索工具 → 基于工具结果生成带溯源的回答

## 目录结构

```
graphrag_pipeline/
├── .env                # Qwen 配置 + KG/JSONL 路径（gitignore）
├── pyproject.toml      # 独立 uv 依赖
├── .venv/              # 独立虚拟环境
├── config.py           # Qwen LLM 配置（适配 LangChain ChatOpenAI）
├── kg_store.py         # KG 内存存储 + 5 类检索原语
├── tools.py            # 6 个 LangChain Tool（绑定 KGStore）
├── agent.py            # LangGraph agent 定义（agent ↔ tools 循环）
├── cli.py              # 命令行测试入口
└── README.md
```

## 设计要点

- **LLM 适配**：用 `langchain_openai.ChatOpenAI` 直接接 Qwen DashScope OpenAI-compatible 端点，复用 `langextract_specification-v1.0.md` 的稳定参数
- **无 embedding**：KG 检索靠关键词 + 属性匹配，不引入 vector store（用户明确要求仅做 KG 问答链路）
- **无 chunk**：原文已被 LangExtract 抽成结构化实体，跳过文档切分阶段
- **6 个 tools**：`kg_summary` / `find_entities` / `list_entities_by_class` / `get_entity_detail` / `get_entity_neighbors` / `find_metrics`
- **代理清理**：启动时 `os.environ.pop` 所有 `*_PROXY`，避免国内 DashScope 经代理失败

## 运行

```bash
# 必须在项目根目录用 --project 锁定 venv（推荐）
cd /path/to/graphragAgent
uv run --project graphrag_pipeline python -m graphrag_pipeline.cli                        # 跑预置 6 道测试题
uv run --project graphrag_pipeline python -m graphrag_pipeline.cli -q "Q1 营业收入是多少？"  # 单问题
uv run --project graphrag_pipeline python -m graphrag_pipeline.cli --interactive           # 交互模式
```

## 实测结果（2026-05-30）

输入：`langextract_src/examples/mineru_to_kg/output/knowledge_graph.json`（17 实体 / 34 三元组）

| 问题 | Tool 调用 | 答案精度 |
|---|---|---|
| 知识图谱里有什么类型的信息？ | `kg_summary` × 1 | ✅ 准确分类与示例 |
| Q1 的营业收入是多少？ | `find_metrics(name=营业收入, group=Q1)` × 1 | ✅ 1,280.50 百万元人民币 |
| Q4 的毛利率是多少？ | `find_metrics(name=毛利率, group=Q4)` × 1 | ✅ 45.2% |
| 全年的净利润是多少？单位是什么？ | `find_metrics(name=净利润, group=全年)` × 1 | ✅ 1035.45 百万元人民币 |
| 图谱里提到了哪些机构？ | `list_entities_by_class(organization)` × 1 | ✅ MinerU |
| 毛利率从 Q1 到 Q4 的变化趋势？ | `find_metrics` + `get_entity_neighbors` × 2 | ✅ 完整趋势分析（42.1%→45.2%） |

每个回答都带 entity_id 与 document_id 溯源链。

## 与 Index Pipeline 的衔接

`.env` 默认指向 `langextract_src/examples/mineru_to_kg/output/knowledge_graph.json`。当你跑完 Index Pipeline（详见 `docs/index_pipeline_specification-v1.0.md`）后，这里直接拿来用。

```
原始 PDF
  ↓ mineru_mvp/.venv → MinerU 解析
  ↓ langextract_src/.venv → LangExtract 抽取 + KG 构建
[knowledge_graph.json]
  ↓ graphrag_pipeline/.venv → Agentic RAG 问答
[带溯源的中文回答]
```

## 已知限制

- 关键词匹配，非 embedding：对同义词（"收入" vs "营收"）依赖 LLM 重写问题
- 无对话记忆：每次 `ask()` 是独立请求；后续可加 LangGraph checkpointer
- 无图遍历查询：当前只支持一跳邻居，多跳查询需要扩展 tool

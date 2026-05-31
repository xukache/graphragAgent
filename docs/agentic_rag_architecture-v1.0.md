# Agentic RAG 技术架构方案 v1.0

基于 MinerU + LangExtract Index Pipeline 的知识图谱输出，使用 LangChain + LangGraph 构建 Agentic RAG 系统。

**前置依赖**：
- `docs/index_pipeline_specification-v1.0.md`（索引阶段输出规范）
- LangChain 官方文档（via MCP：https://docs.langchain.com/mcp）
- LangGraph Agentic RAG 教程（https://docs.langchain.com/oss/python/langgraph/agentic-rag）

---

## 1. 系统全景

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                        GraphRAG Agent 系统                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 索引阶段（离线，已实现）                                          │   │
│  │                                                                   │   │
│  │  原始 PDF → MinerU 解析 → LangExtract 抽取 → KG 构建            │   │
│  │                                                                   │   │
│  │  产物：knowledge_graph.json（实体 + 三元组）                      │   │
│  │        extraction_results.jsonl（原文 + 抽取 + 对齐）             │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                              │                                          │
│                              ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 向量化阶段（离线，待实现）                                        │   │
│  │                                                                   │   │
│  │  extraction_results.jsonl                                         │   │
│  │    → 按 Document 分 chunk                                        │   │
│  │    → Embedding（text-embedding-v3 via DashScope）                 │   │
│  │    → 写入 VectorStore（Chroma / FAISS）                          │   │
│  │                                                                   │   │
│  │  knowledge_graph.json                                             │   │
│  │    → 实体/三元组加载到内存图结构                                   │   │
│  │    → 实体 label + properties → Embedding → 写入 VectorStore      │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                              │                                          │
│                              ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 查询阶段（在线，Agentic RAG，待实现）                             │   │
│  │                                                                   │   │
│  │  用户问题                                                         │   │
│  │    → LangGraph Agent（状态机）                                    │   │
│  │       ├─ 节点 1：generate_query_or_respond（决策）                │   │
│  │       ├─ 节点 2：retrieve_documents（向量检索）                   │   │
│  │       ├─ 节点 3：retrieve_graph（图谱检索）                       │   │
│  │       ├─ 节点 4：grade_documents（相关性评估）                    │   │
│  │       ├─ 节点 5：rewrite_question（问题改写）                     │   │
│  │       └─ 节点 6：generate_answer（生成回答）                      │   │
│  │    → 带溯源的结构化回答                                           │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 技术选型

### 2.1 核心框架

| 组件 | 选型 | 理由 |
| --- | --- | --- |
| Agent 编排 | **LangGraph** | 低层状态机，支持条件分支、循环、人工介入；LangChain 官方推荐用于 Agentic RAG |
| LLM 调用 | **LangChain `init_chat_model`** | 统一接口，支持 OpenAI-compatible（Qwen）、Gemini、Ollama |
| Embedding | **DashScope `text-embedding-v3`** | 已有 API Key，中文效果好，OpenAI-compatible 接口 |
| 向量存储 | **Chroma**（本地持久化） | 轻量、无需外部服务、支持持久化、LangChain 原生集成 |
| 图谱存储 | **内存 dict + JSON**（MVP）→ Neo4j（生产） | MVP 阶段不引入外部数据库；生产阶段用 Cypher 脚本直接导入 |
| 文本分割 | **LangChain `RecursiveCharacterTextSplitter`** | 按 token 分割，支持 overlap，适合中文 |

### 2.2 LLM 配置（复用现有 Qwen）

```python
from langchain.chat_models import init_chat_model

llm = init_chat_model(
    model="qwen3.7-max",
    model_provider="openai",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    api_key=os.environ["QWEN_API_KEY"],
    temperature=0,
)
```

### 2.3 Embedding 配置

```python
from langchain_openai import OpenAIEmbeddings

embeddings = OpenAIEmbeddings(
    model="text-embedding-v3",
    openai_api_key=os.environ["QWEN_API_KEY"],
    openai_api_base="https://dashscope.aliyuncs.com/compatible-mode/v1",
)
```

---

## 3. LangGraph Agent 架构（Agentic RAG）

### 3.1 状态定义

```python
from langgraph.graph import MessagesState
from typing import TypedDict, Annotated

class GraphRAGState(MessagesState):
    """扩展 MessagesState，增加图谱检索上下文。"""
    kg_context: str = ""           # 图谱检索结果
    doc_context: str = ""          # 向量检索结果
    source_refs: list[dict] = []   # 溯源引用
```

### 3.2 节点设计

```text
                    ┌──────────────────────┐
                    │  generate_query_or   │
         ┌────────▶│     _respond         │◀────────┐
         │         └──────────┬───────────┘         │
         │                    │                      │
         │         ┌──────────▼───────────┐         │
         │         │  has_tool_calls?      │         │
         │         └──────┬───────┬───────┘         │
         │           yes  │       │  no              │
         │                ▼       ▼                  │
         │    ┌───────────────┐  ┌──────────┐       │
         │    │ execute_tools │  │   END     │       │
         │    │ (retrieve_*) │  └──────────┘       │
         │    └───────┬───────┘                     │
         │            │                              │
         │            ▼                              │
         │    ┌───────────────┐                     │
         │    │grade_documents│                     │
         │    └───┬───────┬───┘                     │
         │   relevant  irrelevant                   │
         │        │         │                        │
         │        ▼         ▼                        │
         │  ┌──────────┐ ┌────────────────┐         │
         │  │ generate  │ │rewrite_question│─────────┘
         │  │  _answer  │ └────────────────┘
         │  └──────────┘
         │        │
         └────────┘ (如果需要更多信息)
```

### 3.3 工具定义（Agent 可调用的 Tools）

```python
from langchain.tools import tool

@tool
def retrieve_documents(query: str) -> str:
    """从文档向量库中检索与问题相关的文本片段。
    用于回答关于文档具体内容的问题。"""
    docs = vectorstore_retriever.invoke(query)
    return "\n\n".join([
        f"[来源: {d.metadata.get('document_id', '?')}, 页{d.metadata.get('page_idx', '?')}]\n{d.page_content}"
        for d in docs
    ])

@tool
def retrieve_graph(query: str) -> str:
    """从知识图谱中检索实体和关系。
    用于回答关于实体属性、实体间关系、数值指标的问题。"""
    # 1. 用 embedding 相似度找到最相关的实体
    entity_docs = entity_vectorstore.similarity_search(query, k=5)
    entity_ids = [d.metadata["entity_id"] for d in entity_docs]
    # 2. 从图谱中提取这些实体的三元组
    triples = get_triples_for_entities(entity_ids)
    # 3. 格式化为文本
    return format_kg_context(entity_ids, triples)

@tool
def retrieve_metrics(query: str) -> str:
    """从知识图谱中检索数值指标。
    用于回答关于具体数值、统计数据、指标对比的问题。"""
    # 专门针对 metric 类实体的检索
    metrics = get_metrics_by_query(query)
    return format_metrics_table(metrics)
```

### 3.4 节点实现

```python
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

# 节点 1：决策（调用工具 or 直接回答）
def generate_query_or_respond(state: GraphRAGState):
    response = llm.bind_tools(tools).invoke(state["messages"])
    return {"messages": [response]}

# 节点 2：执行工具（LangGraph 内置 ToolNode）
tool_node = ToolNode(tools=[retrieve_documents, retrieve_graph, retrieve_metrics])

# 节点 3：评估文档相关性
def grade_documents(state: GraphRAGState) -> str:
    """条件边：判断检索结果是否相关。"""
    question = state["messages"][0].content
    context = state["messages"][-1].content
    # 用 LLM 评分
    grade = grader_llm.with_structured_output(GradeDocuments).invoke(...)
    return "generate_answer" if grade.binary_score == "yes" else "rewrite_question"

# 节点 4：改写问题
def rewrite_question(state: GraphRAGState):
    original = state["messages"][0].content
    rewritten = llm.invoke(f"改写以下问题以获得更好的检索结果：{original}")
    return {"messages": [{"role": "user", "content": rewritten.content}]}

# 节点 5：生成最终回答
def generate_answer(state: GraphRAGState):
    context = state["messages"][-1].content  # 工具返回的检索结果
    question = state["messages"][0].content
    answer = llm.invoke(
        f"基于以下上下文回答问题。引用来源。\n\n上下文：{context}\n\n问题：{question}"
    )
    return {"messages": [answer]}
```

### 3.5 图构建

```python
graph = StateGraph(GraphRAGState)

# 添加节点
graph.add_node("generate_query_or_respond", generate_query_or_respond)
graph.add_node("tools", tool_node)
graph.add_node("rewrite_question", rewrite_question)
graph.add_node("generate_answer", generate_answer)

# 添加边
graph.set_entry_point("generate_query_or_respond")

# 条件边：有工具调用 → 执行工具；无 → 结束
graph.add_conditional_edges(
    "generate_query_or_respond",
    lambda s: "tools" if s["messages"][-1].tool_calls else END,
)

# 工具执行后 → 评估相关性
graph.add_conditional_edges("tools", grade_documents)

# 相关 → 生成回答；不相关 → 改写问题
graph.add_edge("generate_answer", END)
graph.add_edge("rewrite_question", "generate_query_or_respond")

app = graph.compile()
```

---

## 4. 索引构建流程（从 Index Pipeline 输出到可检索状态）

### 4.1 文档向量化

```python
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document as LCDocument

def index_extractions(jsonl_path: str) -> VectorStore:
    """从 extraction_results.jsonl 构建文档向量库。"""
    annotated_docs = load_jsonl(jsonl_path)

    lc_docs = []
    for doc in annotated_docs:
        lc_docs.append(LCDocument(
            page_content=doc["text"],
            metadata={
                "document_id": doc["document_id"],
                "source_file": doc["document_id"].rsplit("_page_", 1)[0],
                "page_idx": int(doc["document_id"].rsplit("_page_", 1)[1]),
            }
        ))

    # 分割（中文适配）
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=500,
        chunk_overlap=100,
        separators=["\n\n", "\n", "。", "；", "，", " "],
    )
    splits = splitter.split_documents(lc_docs)

    # 向量化 + 存储
    vectorstore = Chroma.from_documents(
        documents=splits,
        embedding=embeddings,
        persist_directory="./chroma_docs",
    )
    return vectorstore
```

### 4.2 实体向量化（用于图谱语义检索）

```python
def index_entities(kg_json_path: str) -> VectorStore:
    """从 knowledge_graph.json 构建实体向量库。"""
    kg = json.loads(Path(kg_json_path).read_text())

    entity_docs = []
    for ent in kg["entities"]:
        # 将实体信息拼接为可检索文本
        text = f"{ent['label']}（{ent['entity_class']}）"
        props = ent.get("properties", {})
        if props:
            text += "：" + "，".join(f"{k}={v}" for k, v in props.items())

        entity_docs.append(LCDocument(
            page_content=text,
            metadata={
                "entity_id": ent["entity_id"],
                "entity_class": ent["entity_class"],
                "label": ent["label"],
            }
        ))

    entity_vectorstore = Chroma.from_documents(
        documents=entity_docs,
        embedding=embeddings,
        persist_directory="./chroma_entities",
    )
    return entity_vectorstore
```

### 4.3 图谱内存加载（用于三元组遍历）

```python
def load_kg_graph(kg_json_path: str) -> dict:
    """加载 KG 到内存，支持按 entity_id 查询三元组。"""
    kg = json.loads(Path(kg_json_path).read_text())

    # 构建邻接表
    adjacency = defaultdict(list)  # entity_id -> list[triple]
    for triple in kg["triples"]:
        adjacency[triple["subject"]].append(triple)
        if isinstance(triple["object"], str):
            adjacency[triple["object"]].append(triple)

    return {
        "entities": {e["entity_id"]: e for e in kg["entities"]},
        "adjacency": adjacency,
        "stats": kg["stats"],
    }
```

---

## 5. 数据流映射（Bridge 输出 → Agentic RAG 输入）

### 5.1 Index Pipeline 输出与 RAG 组件的对应关系

| Bridge 输出文件 | RAG 组件 | 用途 |
| --- | --- | --- |
| `extraction_results.jsonl` | 文档向量库（Chroma） | 原文 chunk 检索，支持语义搜索 |
| `knowledge_graph.json` → `entities` | 实体向量库（Chroma） | 实体语义检索（找到相关实体） |
| `knowledge_graph.json` → `triples` | 内存图结构 | 三元组遍历（找到实体的关系和属性） |
| `knowledge_graph.json` → `stats` | Agent 系统 prompt | 告诉 Agent 图谱中有什么类型的信息 |

### 5.2 检索策略

| 用户问题类型 | 触发的 Tool | 检索路径 |
| --- | --- | --- |
| "文档中提到了什么？" | `retrieve_documents` | 向量库 → 相关 chunk → 原文片段 |
| "XX 是谁？XX 属于哪个机构？" | `retrieve_graph` | 实体向量库 → entity_id → 邻接三元组 |
| "Q1 的营业收入是多少？" | `retrieve_metrics` | 实体向量库（metric 类）→ 精确数值 |
| "对比 Q1 和 Q4 的毛利率" | `retrieve_metrics` + `retrieve_graph` | 多 tool 组合调用 |
| "总结这篇文档的主要内容" | `retrieve_documents` | 全文 chunk 检索 + 摘要生成 |

### 5.3 溯源链路

```text
用户问题
  → Agent 选择 Tool
  → Tool 返回带 metadata 的结果
     - document_id: "sample.pdf_page_0"
     - entity_id: "e_2fd958c0"
     - char_interval: {start_pos: 126, end_pos: 148}
  → Agent 生成回答时引用来源
  → 前端展示：回答 + 来源标注（页码 + 位置）
```

---

## 6. 目录结构规划

```
langextract_src/examples/
└── agentic_rag/                    # Agentic RAG 组件（新建）
    ├── __init__.py
    ├── .env                        # 复用 Qwen 配置
    ├── .gitignore
    ├── README.md
    ├── indexer.py                  # 索引构建（JSONL + KG → Chroma）
    ├── graph.py                    # LangGraph Agent 定义
    ├── tools.py                    # 检索工具定义
    ├── server.py                   # FastAPI 查询服务
    ├── chroma_docs/                # 文档向量库（持久化）
    ├── chroma_entities/            # 实体向量库（持久化）
    └── output/                     # 查询日志
```

**环境**：复用 `langextract_src/.venv`，新增依赖：

```bash
cd langextract_src
uv add langgraph langchain langchain-openai langchain-chroma chromadb
```

---

## 7. 依赖清单

| 包 | 用途 | 版本要求 |
| --- | --- | --- |
| `langgraph` | Agent 状态机编排 | ≥0.2 |
| `langchain` | 核心抽象（tools、chat models、prompts） | ≥0.3 |
| `langchain-openai` | OpenAI-compatible LLM + Embedding 接入 | ≥0.2 |
| `langchain-chroma` | Chroma 向量库集成 | ≥0.2 |
| `chromadb` | 本地向量数据库 | ≥0.5 |
| `langchain-text-splitters` | 文本分割 | ≥0.3 |

---

## 8. 实现步骤

| 步骤 | 内容 | 验证标准 |
| --- | --- | --- |
| 1 | 安装依赖（`uv add langgraph langchain langchain-openai langchain-chroma chromadb langchain-text-splitters`） | `import langgraph, langchain` 成功 |
| 2 | 实现 `indexer.py`：从 Bridge 输出构建 Chroma 向量库 | 文档 + 实体均可检索 |
| 3 | 实现 `tools.py`：三个检索工具 | 每个 tool 独立可调用并返回结果 |
| 4 | 实现 `graph.py`：LangGraph Agent 状态机 | 能回答简单问题并正确选择 tool |
| 5 | 实现 `server.py`：FastAPI 查询接口 | HTTP POST 问题 → 返回带溯源的回答 |
| 6 | 端到端测试：用 Bridge 真实输出跑通 | "Q1 营业收入是多少？" → "1280.50 百万元" |

---

## 9. 与现有系统的集成点

### 9.1 从 Index Pipeline 到 Agentic RAG

```text
Index Pipeline 完成后：
  langextract_src/examples/mineru_to_kg/output/
    ├── extraction_results.jsonl    ──→  indexer.py 读取 → 文档向量库
    └── knowledge_graph.json        ──→  indexer.py 读取 → 实体向量库 + 内存图

Agentic RAG 启动时：
  1. indexer.py 检查 Chroma 是否已构建
  2. 若未构建 → 从 Bridge 输出重建索引
  3. 若已构建 → 直接加载
  4. 启动 LangGraph Agent + FastAPI 服务
```

### 9.2 与可视化前端的集成

现有 `server.py`（Index Pipeline Web UI）可扩展：
- 新增 `/api/query` 端点：接收用户问题 → 调用 LangGraph Agent → 返回回答 + 溯源
- 前端新增"问答"面板：输入框 + 回答展示 + 来源高亮

---

## 10. 关键设计决策

| 决策 | 选择 | 理由 |
| --- | --- | --- |
| Agent 框架 | LangGraph（非 LangChain Agent） | 更细粒度控制，支持条件分支和循环（文档评分 → 改写 → 重试） |
| 向量库 | Chroma（非 FAISS） | 支持持久化 + metadata 过滤 + LangChain 原生集成 |
| 检索策略 | 多 Tool（文档 + 图谱 + 指标） | 让 Agent 自主决定用哪种检索方式，比固定 pipeline 更灵活 |
| Embedding | DashScope text-embedding-v3 | 复用现有 API Key，中文效果好，无需额外配置 |
| 图谱存储 | 内存 dict（MVP） | 避免引入 Neo4j 外部依赖；数据量小时内存足够 |
| 文档评分 | LLM structured output | 比 embedding 相似度阈值更准确，能理解语义相关性 |
| 问题改写 | 单次改写 + 重试 | 避免无限循环；最多改写 1 次后强制生成回答 |

---

## 11. 已知限制与后续演进

| 限制 | 影响 | 演进方向 |
| --- | --- | --- |
| 图谱存内存 | 大规模文档时内存不足 | 接入 Neo4j，用 Cypher 查询 |
| 单次索引 | 新文档需重建索引 | 增量索引（检测新文件 → 追加向量） |
| 无对话记忆 | 多轮对话无上下文 | LangGraph checkpointer 持久化对话状态 |
| 无权限控制 | 所有用户看到所有文档 | 按 document_id 做 metadata 过滤 |
| Embedding 模型固定 | 无法切换 | 抽象为配置项，支持本地 embedding |

---

## 12. 信息来源

- LangGraph Agentic RAG 教程：https://docs.langchain.com/oss/python/langgraph/agentic-rag
- LangGraph Graph API：https://docs.langchain.com/oss/python/langgraph/graph-api
- LangChain RAG 架构对比：https://docs.langchain.com/oss/python/langchain/retrieval#rag-architectures
- LangChain OpenAI 集成：https://docs.langchain.com/oss/python/integrations/providers/openai
- Index Pipeline 规范：`docs/index_pipeline_specification-v1.0.md`
- 现有 Qwen 配置：`langextract_src/examples/qwen_mvp/.env`

> 本架构方案基于 LangChain 官方文档（2026-05 via MCP）和本项目 Index Pipeline 实测输出设计。实现时应以 LangChain/LangGraph 最新 API 为准。

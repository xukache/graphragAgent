# Agentic RAG MVP 规范 v1.0（实测校准版）

本规范以 **本项目实际跑通的 graphrag_pipeline（LangChain + LangGraph + Qwen）输出为准**，定义从「Index Pipeline KG 输出 → Agentic RAG 问答」的完整查询链路，作为 GraphRAG 查询阶段的核心流程。

> 校准原则：**凡本地实际行为与文档描述冲突，一律以本地实际输出为准**，并以「⚠️ 实测校准」标注差异。

**前置规范**：
- `docs/index_pipeline_specification-v1.0.md`（KG 输入规范）
- `docs/langextract_specification-v1.0.md`（Qwen 接入参数稳定组合）
- `docs/agentic_rag_architecture-v1.0.md`（架构设计稿，本规范是其实测落地版）

**实测环境信息**：

| 项 | 实测值 | 来源 |
| --- | --- | --- |
| LangChain | core ≥0.3, openai ≥0.2 | `graphrag_pipeline/pyproject.toml` |
| LangGraph | ≥0.2 | 同上 |
| LLM | Qwen `qwen3.7-max`（DashScope OpenAI-compatible） | `graphrag_pipeline/.env` |
| KG 输入 | 17 实体 / 34 三元组（来自 mineru_to_kg） | `langextract_src/examples/mineru_to_kg/output/knowledge_graph.json` |
| 测试结果 | 6 道预置题全通过；工具调用 1-2 次/题 | `cli.py --interactive` |

**本规范结构**：

1. 完整 Agentic RAG MVP 执行思路 + 测试脚本位置
2. 与 Index Pipeline 的接口契约（输入端）
3. LangChain / LangGraph 关键参数规范（实测稳定组合）
4. Tools 与 Agent 内部数据流
5. 最终问答返回格式规范（输出端）
6. 虚拟环境与运行约束
7. 信息来源

---

## 1. 完整 Agentic RAG MVP 执行思路与脚本位置

### 1.1 脚本存放位置

新增独立组件 `graphrag_pipeline/`，**第三个独立虚拟环境**（与 mineru_mvp、langextract_src 完全隔离）：

| 阶段 | 虚拟环境 | 脚本目录 | 入口 |
| --- | --- | --- | --- |
| 索引（Bridge） | `mineru_mvp/.venv` + `langextract_src/.venv` | 各组件 | 见 bridge spec |
| **查询（Agentic RAG）** | **`graphrag_pipeline/.venv`** | `graphrag_pipeline/` | `cli.py` |

**完整文件清单**：

```
graphrag_pipeline/
├── .env                  # Qwen 配置 + KG_JSON_PATH（gitignore）
├── .gitignore
├── pyproject.toml        # uv 依赖（langgraph + langchain + langchain-openai + fastapi）
├── .venv/                # 独立 venv（Python 3.11）
├── __init__.py
├── config.py             # Qwen → LangChain ChatOpenAI 适配 + 代理清理 + 路径解析
├── kg_store.py           # KG 内存存储 + 5 类检索原语
├── tools.py              # 6 个 LangChain Tool（@tool 装饰器，绑定 KGStore 单例）
├── agent.py              # LangGraph agent 定义（agent ↔ tools 循环，含 SYSTEM_PROMPT）
├── cli.py                # 命令行测试入口（默认题 / 单问题 / 交互模式）
└── README.md
```

### 1.2 完整链路（实测可复现）

```text
[输入] knowledge_graph.json（来自 Index Pipeline）
   │
   ▼  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ┃ 阶段：Agentic RAG 查询（graphrag_pipeline/.venv）
   ┃ ─────────────────────────────────────
   ┃ [1] 启动期：load_kg + build_agent
   ┃     - KGStore.from_json(kg_path)  → 构建 4 个索引（class/label/out_edges/in_edges）
   ┃     - get_llm()                   → Qwen ChatOpenAI（temperature=0）
   ┃     - build_tools(store)          → 注入单例，返回 6 个 @tool
   ┃     - StateGraph(MessagesState)   → agent ↔ tools 循环
   ┃
   ┃ [2] 查询期：ask(agent, question)
   ┃     [2.1] 注入 SYSTEM_PROMPT（首次进入 agent 节点）
   ┃     [2.2] LLM 决策：调用 tools 还是直接回答
   ┃     [2.3] tools_condition 路由：
   ┃            - has tool_calls → ToolNode 执行 → 回到 agent
   ┃            - 无 tool_calls → END
   ┃     [2.4] 多轮工具调用（实测最多 2 跳即可解决复杂问题）
   ┃     [2.5] 最终 AI 消息为答案
   ▼  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[输出] dict {question, answer, tool_calls, tool_call_count}
```

### 1.3 启动方式（实测可复现）

```bash
# 必须在项目根目录用 --project 锁定 venv（cwd 保持根目录让包导入正常）
cd /home/xukai/yixun/projects/graphragAgent

# 跑预置 6 道测试题
uv run --project graphrag_pipeline python -m graphrag_pipeline.cli

# 单问题
uv run --project graphrag_pipeline python -m graphrag_pipeline.cli -q "Q1 的营业收入是多少？"

# 交互模式（多轮提问，Ctrl-C 退出）
uv run --project graphrag_pipeline python -m graphrag_pipeline.cli --interactive

# 指定其他 KG 文件
uv run --project graphrag_pipeline python -m graphrag_pipeline.cli --kg /path/to/knowledge_graph.json
```

### 1.4 实测踩坑与对策（已固化进脚本）

| 现象 | 对策（已实现） |
| --- | --- |
| `ImportError: socksio` | `config.py` 顶部 `os.environ.pop` 所有 `*_PROXY`（DashScope 是国内域名） |
| Qwen `model_id` 路由失败（同 langextract） | 用 `langchain_openai.ChatOpenAI` 直接接 OpenAI-compatible，不走 `init_chat_model` 路由 |
| 在 `cwd=graphrag_pipeline/` 时包导入失败 | 启动时 `cwd` 必须是项目根，用 `uv run --project graphrag_pipeline` 锁定 venv |
| `Path(os.getenv()).strip()` 报错 | `config.py` 先 strip 字符串再构造 `Path` |
| LLM 偶尔不调用工具直接回答 | SYSTEM_PROMPT 明确"不要凭空回答，先选工具检索图谱" |

### 1.5 实测运行结果

输入：`knowledge_graph.json`（17 实体 / 34 三元组，来自 Index Pipeline）

```text
启动加载：
  实体: 17, 三元组: 34, 类别: ['duration', 'metric', 'organization']
  KG 加载耗时: 0.00s（内存）
  Agent 构建耗时: 0.16s（含 6 个 tool 注册 + StateGraph 编译）

6 道预置题全部通过：
| 问题 | tool_calls | 答案精度 |
|---|---|---|
| 知识图谱里有什么类型的信息？ | kg_summary × 1 | ✅ 准确分类 |
| Q1 的营业收入是多少？ | find_metrics(name=营业收入, group=Q1) × 1 | ✅ 1,280.50 百万元人民币 |
| Q4 的毛利率是多少？ | find_metrics(name=毛利率, group=Q4) × 1 | ✅ 45.2% |
| 全年的净利润是多少？单位是什么？ | find_metrics(name=净利润, group=全年) × 1 | ✅ 1035.45 百万元人民币 |
| 图谱里提到了哪些机构？ | list_entities_by_class(organization) × 1 | ✅ MinerU |
| 毛利率从 Q1 到 Q4 的变化趋势？ | find_metrics + get_entity_neighbors × 2 | ✅ 完整趋势分析（42.1%→45.2%） |
```

每个回答都带 `entity_id` + `document_id` 溯源。

---

## 2. 与 Index Pipeline 的接口契约（输入端）

### 2.1 输入文件

Agentic RAG **只消费一个文件**：

| 文件 | 来源 | 用途 |
| --- | --- | --- |
| `knowledge_graph.json` | `langextract_src/examples/mineru_to_kg/output/` | 实体 + 三元组 + stats |

`extraction_results.jsonl` 等其他 Bridge 产物本 MVP **不直接消费**（不需要 embedding，不需要 chunk）。

### 2.2 KG JSON 字段消费方式（KGStore 实测）

依据 `index_pipeline_specification-v1.0.md` 第 5 节，`KGStore` 在加载时构建 4 个索引：

| 来源字段 | 索引结构 | 检索原语 |
| --- | --- | --- |
| `entities[i].entity_id` | `entities: dict[str, dict]` | `get_entity(entity_id)` |
| `entities[i].entity_class` | `class_index: dict[str, list[str]]` | `find_entities_by_class(class)` |
| `entities[i].label + aliases` | `label_index: dict[str_norm, list[str]]` | `find_entities_by_text(query)` |
| `triples[i].subject` | `out_edges: dict[str, list[triple]]` | `get_entity_neighbors(eid)` |
| `triples[i].object`（仅 string 时） | `in_edges: dict[str, list[triple]]` | 同上 |

⚠️ 实测约束：

- `_group_<label>` 虚拟节点也参与 `out_edges` 索引（subject 可以是 entity_id 或虚拟节点）
- `metric` 类专用查询：`find_metrics(metric_name, group)` 直接查 `properties.metric_name + properties.group`
- 字面量边（`object` 为 dict）只通过 `out_edges` 检索，不进入 `in_edges`

### 2.3 实测的实体类别覆盖

本次测试 KG 含 3 类（`organization` / `duration` / `metric`），但 Bridge prompts.py 定义了 9 类，KGStore **不依赖任何特定类别**——`find_entities_by_class` 接受任意字符串，所以接入更复杂的 KG（含 person/disease/drug/relationship 等）时无需修改 graphrag_pipeline 代码。

---

## 3. LangChain / LangGraph 关键参数规范

### 3.1 LLM 配置（Qwen 适配 LangChain 标准组件）

依据 `langextract_specification-v1.0.md` 第 4 节的 Qwen 稳定组合，本 MVP 用 `langchain_openai.ChatOpenAI` 直接对接（不走 `init_chat_model` 路由）：

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="qwen3.7-max",                                          # ← QWEN_LLM_MODEL
    api_key=os.environ["QWEN_API_KEY"],
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1", # ← QWEN_API_BASE
    temperature=0.0,                                              # ← 与 langextract 一致
    timeout=60,
    max_retries=2,
)
```

⚠️ 实测校准：

- 不要用 `init_chat_model("qwen3.7-max")`：与 langextract 同样的"找不到 provider"问题
- `ChatOpenAI` 不需要 `provider="OpenAILanguageModel"`（那是 LangExtract 内部参数）
- `temperature=0` 是 RAG 场景的最佳值（确定性回答 + 工具调用稳定）

### 3.2 LangGraph 状态机（实测稳定组合）

依据 LangChain 官方 Agentic RAG 教程：

```python
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

graph = StateGraph(MessagesState)
graph.add_node("agent", call_model)        # 决策节点（绑定 LLM with tools）
graph.add_node("tools", ToolNode(tools))   # 工具执行节点（自动处理 tool_calls）

graph.add_edge(START, "agent")
graph.add_conditional_edges(
    "agent",
    tools_condition,                        # 内置：检查是否有 tool_calls
    {"tools": "tools", END: END},
)
graph.add_edge("tools", "agent")            # 工具结果回到 agent，可能继续调用工具

agent = graph.compile()
```

实测要点：
- `MessagesState` 是 LangGraph 内置 state，含 `messages: list[BaseMessage]`
- `tools_condition` 是 LangGraph 内置 router，无需自己写条件判断
- `ToolNode` 自动处理 LLM 输出的 `tool_calls`，按工具名分发执行

### 3.3 LLM 工具绑定

```python
llm_with_tools = llm.bind_tools(tools)  # tools = build_tools(store)
```

实测：Qwen `qwen3.7-max` 完全支持 OpenAI 风格的 function calling，包括多工具一次调用、参数推断。

### 3.4 SYSTEM_PROMPT 注入策略

```python
def call_model(state: MessagesState):
    messages = state["messages"]
    if not messages or messages[0].type != "system":
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(messages)
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}
```

⚠️ 实测必要：

- 没有明确 SYSTEM_PROMPT 时，LLM 偶尔会"自信回答"不调用工具
- SYSTEM_PROMPT 必须列举每个 tool 的语义和适用场景，否则 LLM 选错工具
- 末尾要写"如果图谱中没有，直接说没有，不要编造"——防止 hallucination

### 3.5 递归限制

```python
agent.invoke(
    {"messages": [{"role": "user", "content": question}]},
    config={"recursion_limit": 12},  # 实测 6 道题最多用到 4（2 轮 agent ↔ tools）
)
```

`recursion_limit=12` 给复杂问题留余地（最多 6 轮工具调用）。LangGraph 默认 25，本 MVP 设小一点防止跑飞。

### 3.6 配置参数清单（.env）

```bash
# graphrag_pipeline/.env（实测稳定组合）
QWEN_API_KEY=sk-...
QWEN_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_LLM_MODEL=qwen3.7-max

# Index Pipeline 输出路径（相对 graphrag_pipeline/）
KG_JSON_PATH=../langextract_src/examples/mineru_to_kg/output/knowledge_graph.json
EXTRACTIONS_JSONL_PATH=../langextract_src/examples/mineru_to_kg/output/extraction_results.jsonl
```

---

## 4. Tools 与 Agent 内部数据流

### 4.1 6 个 LangChain Tool 实测规范

每个 tool 用 `@tool` 装饰器声明，接受字符串/可选参数，返回 JSON 字符串。

| Tool 名 | 签名 | 适用场景 | 返回字段 |
| --- | --- | --- | --- |
| `kg_summary` | `() -> str` | 开放性问题（"图谱里有什么"） | `{stats, available_classes, sample_entities_per_class}` |
| `find_entities` | `(query, limit=8) -> str` | 关键词搜索（人名/机构/数值） | `{query, count, entities[]}` |
| `list_entities_by_class` | `(entity_class, limit=30) -> str` | 按类别列举 | `{entity_class, count, entities[]}` |
| `get_entity_detail` | `(entity_id) -> str` | 取单实体详情 | 单个 entity 视图 |
| `get_entity_neighbors` | `(entity_id, max_triples=30) -> str` | 一跳关系展开 | `{entity, triples[], neighbors[], out_count, in_count}` |
| `find_metrics` | `(metric_name?, group?, limit=30) -> str` | 数值指标精确过滤 | `{metric_name, group, count, metrics[]}` |

### 4.2 Tool 返回的 entity_view 结构（精简版）

为避免给 LLM 灌噪声，KGStore 返回的实体视图**剔除了不必要的字段**：

```python
{
    "entity_id": str,
    "entity_class": str,
    "label": str,
    "aliases": list[str],
    "properties": dict,           # 全量保留
    "sources": list[dict]         # 最多 3 条，每条只含 document_id + char_interval（去掉 alignment_status）
}
```

### 4.3 Tool 返回的 triple_view 结构

```python
{
    "subject": str,                            # entity_id 或 _group_xxx
    "predicate": str,
    "object": str | dict,                      # 与 KG 原始 schema 一致
    "document_id": str | None                  # 从 metadata.document_id 提取
}
```

⚠️ 实测：tool 返回的 triple **不包含** `metadata` 全字段，只保留 `document_id`。LLM 不需要 `extraction_class` / `warning` 等元数据来生成回答。

### 4.4 内部消息流（实测一例）

问题："Q1 的营业收入是多少？"

```
[1] HumanMessage("Q1 的营业收入是多少？")
[2] → call_model 节点
    ↓ 注入 SystemMessage(SYSTEM_PROMPT)
    ↓ llm_with_tools.invoke([system, human])
[3] AIMessage(content="", tool_calls=[
       {"name": "find_metrics", "args": {"metric_name": "营业收入", "group": "Q1"}}
    ])
[4] → tools_condition → "tools"
[5] → ToolNode 执行 find_metrics
[6] ToolMessage(content='{"count":1,"metrics":[{...value:"1280.50",unit:"百万元人民币"...}]}')
[7] → 回到 call_model 节点
    ↓ llm_with_tools.invoke([system, human, ai_with_tool_call, tool_result])
[8] AIMessage(content="根据知识图谱中的数据：Q1 的营业收入为 1,280.50...")
[9] tools_condition → 无 tool_calls → END
```

`ask()` 函数从最终的 AIMessage 中提取 `content` 作为答案，从所有中间 AIMessage 收集 `tool_calls` 作为调用轨迹。

---

## 5. 最终问答返回格式规范（输出端）

### 5.1 `ask()` 函数返回结构（实测）

```python
result: dict = ask(agent, question)
```

实测顶层字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `question` | str | 用户原始问题（原样回传，便于调用方关联） |
| `answer` | str | 最终的中文回答（含数据 + 溯源描述） |
| `tool_calls` | list[dict] | 工具调用轨迹（按调用顺序） |
| `tool_call_count` | int | 工具调用次数（实测 1-2，复杂问题最多 2） |

### 5.2 `tool_calls[i]` 实测结构

```python
{
    "name": str,    # 工具名（kg_summary / find_metrics / ...）
    "args": dict    # 实际传入参数（已经过 LLM 推断）
}
```

实测真实条目：

```json
{"name": "find_metrics", "args": {"metric_name": "营业收入", "group": "Q1"}}
```

### 5.3 完整 `result` 实测样例

输入：`"Q1 的营业收入是多少？"`

```json
{
  "question": "Q1 的营业收入是多少？",
  "answer": "根据知识图谱中的数据：\n\n**Q1 的营业收入为 1,280.50 百万元人民币。**\n\n- **数据来源**：实体 `e_2fd958c0`，出自文档 `sample.pdf_page_0`（字符位置 252–259）",
  "tool_calls": [
    {
      "name": "find_metrics",
      "args": {"metric_name": "营业收入", "group": "Q1"}
    }
  ],
  "tool_call_count": 1
}
```

复杂问题（多跳）实测样例：

输入：`"毛利率从 Q1 到 Q4 的变化趋势？"`

```json
{
  "question": "毛利率从 Q1 到 Q4 的变化趋势？",
  "answer": "根据知识图谱中的数据，**毛利率从 Q1 到 Q4 呈现逐季稳步上升的趋势**：\n\n| 季度 | 毛利率 | 环比变化 |\n| Q1 | 42.1% | — |\n| Q2 | 43.8% | +1.7pp |\n| Q3 | 44.5% | +0.7pp |\n| Q4 | 45.2% | +0.7pp |\n| 全年 | 43.9% | — |\n\n趋势总结：持续上升，全年累计提升 3.1 个百分点。\n数据来源：Q1: e_72de37e1 | Q2: e_85b06dc6 | ... 均出自 sample.pdf_page_0",
  "tool_calls": [
    {"name": "find_metrics", "args": {"metric_name": "毛利率"}},
    {"name": "get_entity_neighbors", "args": {"entity_id": "e_72de37e1"}}
  ],
  "tool_call_count": 2
}
```

### 5.4 答案文本中的溯源约定（SYSTEM_PROMPT 强制）

实测 SYSTEM_PROMPT 要求 LLM 在 `answer` 文本中包含：

| 溯源元素 | 来源 | 文本格式（实测） |
| --- | --- | --- |
| 实体 ID | tool 返回的 `entity_id` | `` 实体 `e_xxxxxxxx` `` 或行内代码块 |
| 文档 ID | tool 返回的 `sources[i].document_id` | `` 文档 `sample.pdf_page_0` `` |
| 字符位置 | tool 返回的 `sources[i].char_interval` | `字符位置 252–259` |

⚠️ 实测校准：LLM 偶尔会用全角括号 `（` 或不同的连字符 `-` / `–`，下游代码不要用正则严格匹配格式，建议从 `tool_calls` 反查 entity_id 来做精确溯源。

### 5.5 失败 / 找不到答案时的格式

实测 SYSTEM_PROMPT 包含"如果图谱中确实没有相关信息，直接说'知识图谱中未找到相关信息'，不要编造"，所以失败答案形如：

```json
{
  "question": "公司 CEO 是谁？",
  "answer": "知识图谱中未找到关于公司 CEO 的相关信息。当前图谱主要包含 MinerU 公司 2024 财年的财务指标数据（营业收入、净利润、毛利率），未涉及高管信息。",
  "tool_calls": [
    {"name": "find_entities", "args": {"query": "CEO"}},
    {"name": "list_entities_by_class", "args": {"entity_class": "person"}}
  ],
  "tool_call_count": 2
}
```

`tool_call_count > 0` 但答案显式说"未找到"——这是**正确行为**，不是 bug。

### 5.6 异常情况

| 情况 | `answer` 行为 | `tool_calls` 行为 |
| --- | --- | --- |
| LLM 直接回答（不调工具） | 包含答案文本 | 空数组 `[]`，count=0 |
| 工具调用但 LLM 最终判断无法回答 | "知识图谱中未找到..." | 含调用轨迹 |
| `recursion_limit` 触发 | LangGraph 抛 `GraphRecursionError` | 由 caller 捕获处理 |
| KG 加载失败 | 不进入 `ask()`；启动期 `FileNotFoundError` | — |

调用方应在 `ask()` 外层用 `try/except` 包住，捕获 `GraphRecursionError`、网络错误等。

### 5.7 下游消费建议

| 下游用途 | 应使用字段 |
| --- | --- |
| 直接展示给用户 | `answer` |
| 调试 / 审计 / 分析工具效率 | `tool_calls` + `tool_call_count` |
| 精确溯源（前端高亮） | 从 `tool_calls[i].args` 反查 KG，找到对应 entity_id 与 char_interval |
| 流式 UI（逐 token 显示） | 改用 `agent.stream()` 替代 `agent.invoke()`（本 MVP 未实现，预留扩展点） |

---

## 6. 虚拟环境与运行约束（必读）

graphrag_pipeline 是项目的**第三个独立虚拟环境**。完整端到端链路跨**三个 venv 协同**：

### 6.1 三个 venv 的职责边界

| 组件 | venv 路径 | 职责 |
| --- | --- | --- |
| `mineru_mvp` | `mineru_mvp/.venv` | MinerU 解析（reportlab + requests） |
| `langextract_src` | `langextract_src/.venv` | LangExtract 抽取 + KG 构建（langextract + openai） |
| **`graphrag_pipeline`** | **`graphrag_pipeline/.venv`** | **Agentic RAG 问答（langgraph + langchain + langchain-openai）** |

三个 venv **完全隔离**：
- 不共享依赖（实测：langgraph 只在 graphrag_pipeline 中；langextract 只在 langextract_src 中）
- 跨阶段只通过**文件 IO**传递（KG_JSON_PATH 指向 `../langextract_src/examples/mineru_to_kg/output/knowledge_graph.json`）
- 启动入口靠 `--project` 参数锁定 venv

### 6.2 启动路径

```bash
# 必须在项目根目录用 --project 锁定 graphrag_pipeline 的 venv
# cwd 保持在根目录，让 Python 包导入正常工作（包名 graphrag_pipeline）
cd /home/xukai/yixun/projects/graphragAgent
uv run --project graphrag_pipeline python -m graphrag_pipeline.cli [选项]
```

⚠️ 不要 `cd graphrag_pipeline && uv run python -m graphrag_pipeline.cli`：cwd 进入子目录后包导入会失败（`ModuleNotFoundError: graphrag_pipeline`）。

### 6.3 不允许的操作

- ❌ 在 `mineru_mvp/.venv` 或 `langextract_src/.venv` 中跑 graphrag_pipeline（会缺 langgraph）
- ❌ 在 graphrag_pipeline 中 import langextract 或 mineru 的 Python 模块（应通过 KG_JSON_PATH 文件接口）
- ❌ 在脚本里硬编码 Qwen Key（必须通过 `.env`）
- ❌ 提交 `.env` / `.venv/` 到 git

### 6.4 跨阶段数据传递

```
[阶段 1] mineru_mvp/output/                        ← MinerU 解析
            ↓ （文件 IO，跨 venv）
[阶段 2] langextract_src/examples/mineru_to_kg/output/  ← Bridge KG
            ↓ （文件 IO，跨 venv）
[阶段 3] graphrag_pipeline → ask() → JSON dict     ← Agentic RAG
            ↓
        前端 / API / 调用方
```

详细规则参见 `AGENTS.md` 与 `.kiro/steering/environment-isolation.md`。

---

## 7. 信息来源

- 前置规范：`docs/index_pipeline_specification-v1.0.md`、`docs/langextract_specification-v1.0.md`、`docs/agentic_rag_architecture-v1.0.md`
- 实测脚本：`graphrag_pipeline/`（config.py / kg_store.py / tools.py / agent.py / cli.py）
- 实测 KG 输入：`langextract_src/examples/mineru_to_kg/output/knowledge_graph.json`（17 实体 / 34 三元组）
- 实测查询输出：6 道预置题全通过，工具调用 1-2 次/题（2026-05-30）
- LangChain 文档：https://docs.langchain.com/oss/python/langgraph/agentic-rag（via MCP）
- LLM 后端：阿里千问 DashScope OpenAI-compatible（model=qwen3.7-max）

> 凡本规范「⚠️ 实测校准」处，均以本地实际输出为准。后续接入更复杂 KG（含 person/relationship/disease 等类别）或扩展 tool（增量索引、对话记忆）时，应在 `graphrag_pipeline/output/` 下补充实测，并据此继续校准本规范。

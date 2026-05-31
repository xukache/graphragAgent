# GraphRAG 后端服务规范 v1.0（设计文档）

本规范定义多模态 RAG 问答系统的后端服务架构与 API 接口契约，作为前端 / 多客户端的统一接入层。

> 本文档是**设计规范**（尚未实现），是落地实现的契约。实现完成后将与现有 `*-v1.0.md` 风格一致地补充「实测校准」章节。

**前置规范**（消费下游的输入输出契约）：
- `docs/mineru_specification-v1.0.md`（MinerU 文档解析输入/输出）
- `docs/langextract_specification-v1.0.md`（LangExtract 抽取参数）
- `docs/index_pipeline_specification-v1.0.md`（索引阶段的 KG 输出契约）
- `docs/agentic_rag_mvp_specification-v1.0.md`(查询阶段 ask() 返回契约)

**关键设计决策**（头脑风暴阶段已确认）：

| 决策 | 选择 | 理由 |
| --- | --- | --- |
| 服务定位 | 先服务前端 + 接口预留多客户端扩展 | 短期落地 + 长期可扩展 |
| 进度推送 | SSE 流式推送（兼容轮询兜底） | 体验好且单机 MVP 可承受 |
| 存储方案 | SQLite（元数据/任务/会话）+ 文件系统（大块 JSON 产物） | 重启不丢状态 + 大数据高效 |
| 查询作用域 | 单文档（每次问答必须指定 document_id） | 语义清晰 + 性能可控 |
| 会话状态 | 后端轻量 session（绑定文档 + 历史 message） | 多轮上下文友好 |
| Venv 策略 | 后端与 graphrag_pipeline 共享 venv；mineru / langextract 通过 subprocess 调用 | 避免依赖冲突 + 复用 KGStore/agent |

**本文档结构**：

1. 系统架构与组件边界
2. 数据模型（SQLite + 文件系统）
3. API 接口规范（13 个端点）
4. 工程化细节（subprocess 编排 / EventBus / Agent 缓存）
5. 项目结构与启动
6. MVP 范围与后续扩展点

---

## 1. 系统架构与组件边界

### 1.1 全景图

```text
┌──────────────────────────────────────────────────────────────────────┐
│                       前端 / 多客户端                                 │
└──────────────────────────────────────────────────────────────────────┘
                              │ HTTP / SSE
                              ▼
┌──────────────────────────────────────────────────────────────────────┐
│  graphrag_backend/   （新增组件，第 4 个独立 venv）                   │
│  ─────────────────────────────────────────────────────────────────   │
│  FastAPI                                                              │
│  ├─ /api/documents     文档上传 / 列表 / 删除 / 索引状态              │
│  ├─ /api/tasks/{id}/events   SSE 进度推送                             │
│  ├─ /api/sessions      会话生命周期（绑定 document_id）               │
│  └─ /api/sessions/{id}/messages   多轮问答（SSE 流式 token）          │
│                                                                       │
│  内部模块                                                             │
│  ├─ orchestrator/   异步任务编排（mineru → langextract → kg）         │
│  ├─ agent_runner/   持有 KG + Agent，按 document_id 缓存               │
│  ├─ store/          SQLite + 文件系统访问                             │
│  └─ schemas/        Pydantic 请求/响应模型                            │
└──────────────────────────────────────────────────────────────────────┘
       │                    │                    │
       ▼                    ▼                    ▼
   subprocess           subprocess           import
   mineru_mvp/.venv     langextract_src/     graphrag_pipeline
                        .venv                .venv  ← 同一个

┌──────────────────────────────────────────────────────────────────────┐
│  data/                  工程化数据存储                                │
│  ├─ index.db            SQLite：documents / tasks / sessions / msg   │
│  └─ documents/{doc_id}/                                               │
│        ├─ source.{ext}              用户上传的原始文件                │
│        ├─ mineru/                   MinerU 输出                       │
│        ├─ kg/                                                         │
│        │    ├─ knowledge_graph.json  ← Agent 加载                     │
│        │    ├─ extraction_results.jsonl                               │
│        │    └─ visualization.html                                     │
│        ├─ logs/                     subprocess stdout/stderr          │
│        └─ meta.json                 文档元数据快照                    │
└──────────────────────────────────────────────────────────────────────┘
```

### 1.2 跨 venv 调用方式

后端不能 import 三个 venv 的代码（依赖冲突）。两类调用方式：

| 子流程 | 当前 venv | 后端调用方式 |
| --- | --- | --- |
| MinerU 解析 | `mineru_mvp/.venv` | **subprocess** 调用 `mineru_mvp/.venv/bin/python -m mineru_mvp.runner_cli` |
| LangExtract + KG 构建 | `langextract_src/.venv` | **subprocess** 调用 `langextract_src/.venv/bin/python -m examples.mineru_to_kg.runner_cli` |
| Agentic RAG 问答 | `graphrag_pipeline/.venv` | **同 venv 直接 import**（后端 = graphrag_pipeline 的服务化封装） |

**关键决策**：后端 venv 与 `graphrag_pipeline/.venv` **合并**——后端通过 `[tool.uv.sources]` 把 graphrag_pipeline 安装进来，索引阶段通过 subprocess 跨 venv（绕开依赖冲突），查询阶段直接 `from graphrag_pipeline.kg_store import KGStore`。

### 1.3 组件职责

| 模块 | 职责 | 不该做的事 |
| --- | --- | --- |
| `routers/` | HTTP 处理：参数校验、依赖注入、调用 service、返回响应 | 不写业务逻辑 |
| `orchestrator/` | 异步任务编排（subprocess 串联、进度透传、状态更新） | 不直接处理 HTTP |
| `agent_runner/` | KGStore + Agent 实例的 LRU 缓存 | 不直接读 KG JSON 文件 |
| `store/` | SQLite ORM + 文件系统操作 | 不暴露 SQL 给上层 |
| `events/` | EventBus 进程内消息总线 | 不持久化（持久化在 store 层） |
| `schemas/` | 请求 / 响应 / 错误的 Pydantic 模型 | 不含业务逻辑 |

---

## 2. 数据模型

### 2.1 SQLite 表（`data/index.db`）

只存元数据和状态，**不存大块 JSON**（KG / 抽取结果走文件系统）。

#### `documents` 表

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `document_id` | TEXT PRIMARY KEY | UUID v4 |
| `original_filename` | TEXT | 用户上传的原始文件名 |
| `file_size_bytes` | INTEGER | 字节数 |
| `mime_type` | TEXT | 例如 `application/pdf` |
| `status` | TEXT | `pending` / `parsing` / `extracting` / `building_kg` / `ready` / `failed` |
| `created_at` | INTEGER | Unix 毫秒 |
| `updated_at` | INTEGER | Unix 毫秒 |
| `error_message` | TEXT NULL | 失败时的错误原因 |
| `kg_stats_json` | TEXT NULL | KG ready 后冗余存 stats，列表页直接展示 |

索引：`idx_documents_status_created`(status, created_at DESC)

#### `tasks` 表（索引任务，1 文档 1 任务）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `task_id` | TEXT PRIMARY KEY | UUID v4 |
| `document_id` | TEXT | FK → documents |
| `state` | TEXT | `queued` / `parsing` / `extracting` / `building_kg` / `done` / `failed` |
| `progress_pct` | INTEGER | 0-100 |
| `current_stage` | TEXT | 阶段描述（中文，给前端显示） |
| `started_at` | INTEGER NULL | |
| `finished_at` | INTEGER NULL | |
| `error_message` | TEXT NULL | |
| `events_json` | TEXT | 事件历史 JSON 数组（SSE 断线重连回放） |

索引：`idx_tasks_document_id`(document_id)

#### `sessions` 表

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `session_id` | TEXT PRIMARY KEY | UUID v4 |
| `document_id` | TEXT | FK → documents（创建时确定，不可改） |
| `title` | TEXT NULL | 用户自定义；默认取首问题前 30 字 |
| `created_at` | INTEGER | |
| `updated_at` | INTEGER | 最后一条消息时间 |
| `message_count` | INTEGER | 累计消息数（user + assistant） |

索引：`idx_sessions_document_updated`(document_id, updated_at DESC)

#### `messages` 表

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `message_id` | TEXT PRIMARY KEY | UUID v4 |
| `session_id` | TEXT | FK → sessions |
| `role` | TEXT | `user` / `assistant` |
| `content` | TEXT | 消息文本 |
| `tool_calls_json` | TEXT NULL | assistant 消息的工具调用轨迹（来自 `agentic_rag_mvp_specification-v1.0.md` 第 5.2 节） |
| `created_at` | INTEGER | |
| `latency_ms` | INTEGER NULL | assistant 消息的端到端耗时 |

索引：`idx_messages_session_created`(session_id, created_at)

### 2.2 文件系统布局

```
data/
├── index.db                              # SQLite 单文件
└── documents/
    └── {document_id}/                    # 每个文档独立目录（自包含）
        ├── meta.json                     # SQLite 元数据快照（冗余备份）
        ├── source.pdf                    # 原始上传文件（保留 mime_type 对应扩展名）
        ├── mineru/                       # MinerU 解析输出
        │   ├── result.zip
        │   ├── full.md
        │   ├── {uuid}_content_list.json
        │   ├── {uuid}_content_list_v2.json
        │   ├── {uuid}_model.json
        │   ├── layout.json
        │   ├── {uuid}_origin.pdf
        │   └── images/
        ├── kg/                           # LangExtract + KG 构建输出
        │   ├── knowledge_graph.json      # ★ 查询阶段加载
        │   ├── knowledge_graph.cypher
        │   ├── knowledge_graph.md
        │   ├── extraction_results.jsonl
        │   ├── extractions_raw.json
        │   └── visualization.html
        └── logs/                         # subprocess stdout/stderr
            ├── mineru.stdout.log
            ├── mineru.stderr.log
            ├── langextract.stdout.log
            └── langextract.stderr.log
```

**关键约定**：
- 每个文档目录**自包含**——可单独打包 / 删除 / 备份
- 删除文档 = 删 `documents/{doc_id}/` 整个目录 + SQLite 行
- 失败文档保留已生成部分（便于排查），但 status=`failed` 不出现在 ready 列表

### 2.3 状态机（`documents.status`）

```
pending → parsing → extracting → building_kg → ready
   │         │          │             │
   └─────────┴──────────┴─────────────┴─→ failed
```

`tasks.state` 与 `documents.status` 同步更新（document.status 是面向用户的状态，task.state 是面向后端调度的更细粒度状态，二者一一对应）。

### 2.4 不进数据库的内容

明确**不**存 SQLite：
- KG 实体 / 三元组（在 `kg/knowledge_graph.json`）
- 抽取明细（在 `kg/extraction_results.jsonl`）
- 文档原始文本 / 图片（在 `mineru/` 目录）
- SSE 实时事件流（订阅时实时推送；历史事件存 `tasks.events_json` 用于断线重连回放）

理由：JSON 大块数据进 SQLite 没有查询收益，反而增加序列化开销。

---

## 3. API 接口规范

### 3.1 通用约定

#### 请求 / 响应

- 上传：`multipart/form-data`；其他：`application/json`
- 时间统一 Unix 毫秒（int）
- 字段命名一律 `snake_case`
- 分页：`?page=1&page_size=20`（默认 20，最大 100）
- 鉴权：MVP 不做，预留 `Authorization: Bearer` 头

#### 错误响应（HTTP 4xx/5xx）

```json
{
  "error": {
    "code": "DOCUMENT_NOT_FOUND",
    "message": "文档不存在或已删除",
    "details": {"document_id": "abc-123"}
  },
  "trace_id": "req-2026-05-31-..."
}
```

错误码：

| 错误码 | HTTP | 说明 |
| --- | --- | --- |
| `INVALID_REQUEST` | 400 | 参数错误 |
| `UNSUPPORTED_FILE_TYPE` | 400 | 文件类型不支持 |
| `FILE_TOO_LARGE` | 400 | 超过 200MB |
| `DOCUMENT_NOT_FOUND` | 404 | |
| `SESSION_NOT_FOUND` | 404 | |
| `TASK_NOT_FOUND` | 404 | |
| `DOCUMENT_NOT_READY` | 409 | 文档未索引完成 |
| `MINERU_FAILED` | 500 | |
| `EXTRACTION_FAILED` | 500 | |
| `KG_BUILD_FAILED` | 500 | |
| `LLM_TIMEOUT` | 502 | |
| `LLM_ERROR` | 502 | |

### 3.2 文档管理（5 个端点）

#### `POST /api/documents`  上传文档

**请求**：`multipart/form-data`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `file` | binary | ✅ | 文件本体 |
| `original_filename` | string | 否 | 覆盖默认文件名 |

支持类型（依据 `mineru_specification-v1.0.md` 第 1 节）：`pdf` / `doc` / `docx` / `ppt` / `pptx` / `xls` / `xlsx` / `png` / `jpg` / `jpeg` / `bmp` / `webp` / `html`。大小上限 200MB。

**响应**（HTTP 201）：

```json
{
  "document_id": "doc-3a7f...",
  "task_id": "task-89b1...",
  "original_filename": "财报.pdf",
  "file_size_bytes": 1248320,
  "status": "pending",
  "created_at": 1748600000123,
  "events_url": "/api/tasks/task-89b1.../events"
}
```

调用方收到响应后**立即**可连 `events_url` 拿 SSE 进度（任务异步执行，已在后台 enqueue）。

#### `GET /api/documents`  列出文档

**Query**：`?status=ready&page=1&page_size=20&sort=created_at_desc`

可选参数：
- `status`：按状态过滤（不传则返回所有）
- `sort`：`created_at_desc`（默认）/ `created_at_asc` / `updated_at_desc`

**响应**：

```json
{
  "items": [
    {
      "document_id": "doc-3a7f...",
      "original_filename": "财报.pdf",
      "file_size_bytes": 1248320,
      "mime_type": "application/pdf",
      "status": "ready",
      "created_at": 1748600000123,
      "updated_at": 1748600142001,
      "kg_stats": {
        "entity_count": 17,
        "triple_count": 34,
        "by_class": {"metric": 15, "organization": 1, "duration": 1}
      }
    }
  ],
  "total": 8,
  "page": 1,
  "page_size": 20
}
```

`kg_stats` 来自 `documents.kg_stats_json` 冗余字段，文档 `ready` 时才有；其他状态为 `null`。

#### `GET /api/documents/{document_id}`  文档详情

**响应**：单条文档完整信息：

```json
{
  "document_id": "doc-3a7f...",
  "original_filename": "财报.pdf",
  "file_size_bytes": 1248320,
  "mime_type": "application/pdf",
  "status": "ready",
  "created_at": 1748600000123,
  "updated_at": 1748600142001,
  "error_message": null,
  "kg_stats": {...},
  "current_task": {
    "task_id": "task-89b1...",
    "state": "done",
    "progress_pct": 100
  }
}
```

`status=failed` 时含 `error_message`。

#### `GET /api/documents/{document_id}/kg`  获取知识图谱

**响应**：直接返回 `kg/knowledge_graph.json` 的内容（与 `index_pipeline_specification-v1.0.md` 第 5.2 节定义一致）

```json
{
  "entities": [...],
  "triples": [...],
  "stats": {...}
}
```

文档未 `ready` 时返回 409 `DOCUMENT_NOT_READY`。

#### `DELETE /api/documents/{document_id}`  删除文档

级联删除：
1. evict AgentRunner LRU 缓存
2. 删除 SQLite 文档行 + 关联 sessions + messages + tasks
3. 删除 `data/documents/{document_id}/` 整个目录

返回 204 No Content。

### 3.3 索引进度（SSE）

#### `GET /api/tasks/{task_id}/events`  订阅任务进度

**响应**：`Content-Type: text/event-stream`

事件类型（每条 `event:` + `data:` + 空行）：

| event | 说明 |
| --- | --- |
| `stage_start` | 进入新阶段 |
| `progress` | 阶段内进度推进（pct + detail） |
| `stage_done` | 阶段完成（含耗时） |
| `complete` | 全部完成（终态） |
| `error` | 失败（终态） |

事件示例：

```
event: stage_start
data: {"stage": "parsing", "message": "正在调用 MinerU 解析", "ts": 1748600001000}

event: progress
data: {"stage": "parsing", "pct": 35, "detail": "MinerU state=running, 3/10 pages", "ts": 1748600015000}

event: stage_done
data: {"stage": "parsing", "elapsed_ms": 18500, "ts": 1748600018500}

event: stage_start
data: {"stage": "extracting", "message": "LangExtract 抽取中（1/3 chunks）", "ts": 1748600018600}

event: progress
data: {"stage": "extracting", "pct": 65, "detail": "已处理 2/3 chunks", "ts": 1748600045000}

event: stage_done
data: {"stage": "building_kg", "elapsed_ms": 800, "ts": 1748600061000}

event: complete
data: {
  "document_id": "doc-3a7f...",
  "status": "ready",
  "kg_stats": {"entity_count": 17, "triple_count": 34, "by_class": {...}},
  "elapsed_ms": 61234,
  "ts": 1748600061234
}
```

失败时：

```
event: error
data: {"stage": "extracting", "code": "EXTRACTION_FAILED", "message": "LLM 连续 3 次返回空 JSON", "ts": ...}
```

**断线重连**：客户端可带 `Last-Event-ID` 头，后端从 `tasks.events_json` 历史事件中回放未推送的部分。任务终态（`complete` / `error`）后连接关闭。

#### `GET /api/tasks/{task_id}`  任务状态快照（轮询兜底）

为不支持 SSE 的客户端提供：

```json
{
  "task_id": "task-89b1...",
  "document_id": "doc-3a7f...",
  "state": "extracting",
  "progress_pct": 65,
  "current_stage": "LangExtract 抽取中（2/3 chunks）",
  "started_at": 1748600001000,
  "finished_at": null,
  "events": [
    {"type": "stage_start", "stage": "parsing", "ts": ...},
    ...
  ]
}
```

### 3.4 会话与问答（5 个端点）

#### `POST /api/sessions`  创建会话

**请求**：

```json
{
  "document_id": "doc-3a7f...",
  "title": "财报分析"
}
```

文档必须 `ready`，否则 409。

**响应**（HTTP 201）：

```json
{
  "session_id": "sess-c8d2...",
  "document_id": "doc-3a7f...",
  "title": "财报分析",
  "created_at": 1748600100000,
  "message_count": 0
}
```

#### `GET /api/sessions?document_id={id}`  列出某文档下的所有会话

`document_id` 必填。返回分页列表，按 `updated_at` 降序。

```json
{
  "items": [
    {
      "session_id": "sess-...",
      "document_id": "doc-...",
      "title": "财报分析",
      "created_at": ...,
      "updated_at": ...,
      "message_count": 6
    }
  ],
  "total": 3,
  "page": 1,
  "page_size": 20
}
```

#### `POST /api/sessions/{session_id}/messages`  发送问题

**请求**：

```json
{
  "content": "Q1 的营业收入是多少？",
  "stream": true
}
```

`stream` 默认 `true`（SSE）。`false` 时同步返回完整结果。

**响应（stream=true，Content-Type: text/event-stream）**：

事件类型：

| event | 说明 |
| --- | --- |
| `tool_call` | LLM 决定调用工具（含 name + args） |
| `tool_result` | 工具执行完成（含简要结果摘要） |
| `token` | 答案逐 token 推送 |
| `complete` | 完整答案（含 message_id / latency_ms） |
| `error` | 失败 |

事件示例：

```
event: tool_call
data: {"name": "find_metrics", "args": {"metric_name": "营业收入", "group": "Q1"}, "ts": ...}

event: tool_result
data: {"name": "find_metrics", "result_summary": "找到 1 个 metric 实体", "ts": ...}

event: token
data: {"text": "根据知识图谱"}

event: token
data: {"text": "中的数据：\n\n**Q1"}

... (逐 token 推送) ...

event: complete
data: {
  "message_id": "msg-...",
  "answer": "根据知识图谱中的数据：\n\n**Q1 的营业收入为 1,280.50 百万元人民币。**\n\n- **数据来源**：实体 `e_2fd958c0`，出自文档 `sample.pdf_page_0`",
  "tool_calls": [
    {"name": "find_metrics", "args": {"metric_name": "营业收入", "group": "Q1"}}
  ],
  "tool_call_count": 1,
  "latency_ms": 3420,
  "ts": ...
}
```

**响应（stream=false，application/json）**：

```json
{
  "message_id": "msg-...",
  "session_id": "sess-c8d2...",
  "question": "Q1 的营业收入是多少？",
  "answer": "根据知识图谱中的数据：\n\n**Q1 的营业收入为 1,280.50 百万元人民币。**\n\n- **数据来源**：实体 `e_2fd958c0`，出自文档 `sample.pdf_page_0`",
  "tool_calls": [
    {"name": "find_metrics", "args": {"metric_name": "营业收入", "group": "Q1"}}
  ],
  "tool_call_count": 1,
  "latency_ms": 3420,
  "created_at": 1748600100123
}
```

字段对应 `agentic_rag_mvp_specification-v1.0.md` 第 5 节。

**多轮上下文**：后端从 SQLite 读该 session 的 message 历史，拼成 messages 列表传给 `agent.invoke()`（系统提示 + 历史 user/assistant + 当前 user）。同会话连续提问自然有上下文。

#### `GET /api/sessions/{session_id}/messages`  会话历史

分页返回所有 messages（按 `created_at` 升序）：

```json
{
  "items": [
    {"message_id": "msg-...", "role": "user", "content": "Q1 的营业收入是多少？", "created_at": ...},
    {"message_id": "msg-...", "role": "assistant", "content": "...", "tool_calls": [...], "tool_call_count": 1, "latency_ms": 3420, "created_at": ...},
    {"message_id": "msg-...", "role": "user", "content": "Q4 呢？", "created_at": ...},
    {"message_id": "msg-...", "role": "assistant", "content": "...", "tool_calls": [...], "tool_call_count": 1, "latency_ms": 2980, "created_at": ...}
  ],
  "total": 4,
  "page": 1,
  "page_size": 50
}
```

#### `DELETE /api/sessions/{session_id}`  删除会话

级联删除所有 messages。返回 204。

### 3.5 健康检查

#### `GET /api/health`

```json
{
  "status": "ok",
  "version": "0.1.0",
  "uptime_seconds": 3601,
  "checks": {
    "sqlite": "ok",
    "data_dir": "ok",
    "mineru_subprocess": "ok",
    "langextract_subprocess": "ok",
    "qwen_llm": "ok"
  }
}
```

各 `checks` 项是启动时一次性探活的结果（subprocess 检查能否调用对应 venv 的 Python；llm 不发真实请求，只验证配置存在）。

### 3.6 接口清单速查（13 个）

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/documents` | 上传文档（异步索引） |
| GET | `/api/documents` | 列出文档 |
| GET | `/api/documents/{id}` | 文档详情 |
| GET | `/api/documents/{id}/kg` | 获取 KG JSON |
| DELETE | `/api/documents/{id}` | 删除文档 |
| GET | `/api/tasks/{id}/events` | **SSE 推送索引进度** |
| GET | `/api/tasks/{id}` | 任务状态快照（轮询兜底） |
| POST | `/api/sessions` | 创建会话 |
| GET | `/api/sessions` | 列出会话（按文档过滤） |
| DELETE | `/api/sessions/{id}` | 删除会话 |
| POST | `/api/sessions/{id}/messages` | **发送问题（SSE / 同步）** |
| GET | `/api/sessions/{id}/messages` | 会话历史 |
| GET | `/api/health` | 健康检查 |

---

## 4. 工程化细节

### 4.1 索引任务编排（subprocess + 进度事件）

#### 调用链

```
POST /api/documents
   ↓ 落盘 source.pdf + INSERT documents/tasks（status=pending）
   ↓ 立即返回 {document_id, task_id, events_url}
   ↓ asyncio.create_task(IndexJob.run(task_id))
   │
   ▼
后台 worker 执行 IndexJob.run():
   [1] subprocess: mineru_mvp/.venv/bin/python -m mineru_mvp.runner_cli
       --input data/documents/{doc_id}/source.pdf
       --output-dir data/documents/{doc_id}/mineru
       --progress-fd 3
       
       worker 读 fd=3 的每一行 → 解析 JSON → push 到 EventBus
                                            → append 到 tasks.events_json
                                            → 转 SSE 推给订阅者
       
   [2] subprocess: langextract_src/.venv/bin/python \
                   -m examples.mineru_to_kg.runner_cli
       --mineru-output data/documents/{doc_id}/mineru
       --output-dir   data/documents/{doc_id}/kg
       --progress-fd 3
       
   [3] 同 venv 直接 import：
       from graphrag_pipeline.kg_store import KGStore
       store = KGStore.from_json(data/documents/{doc_id}/kg/knowledge_graph.json)
       agent = build_agent(store)
       agent_runner.cache_set(doc_id, store, agent)
       
   [4] UPDATE documents SET status='ready', kg_stats_json=...
       UPDATE tasks SET state='done', progress_pct=100
       push complete event → 关闭 SSE 连接
```

#### Subprocess 接口约定

需要在两个旧组件中**新增轻量 CLI runner**（不改原 `pipeline.py`，避免破坏 MVP）：

| 组件 | 新增文件 | 作用 |
| --- | --- | --- |
| `mineru_mvp/` | `runner_cli.py` | 包装现有逻辑，接受 `--input` / `--output-dir` / `--progress-fd`；把 MinerU 内部状态（waiting-file → pending → running → done）写为 JSON 行到 fd 3 |
| `langextract_src/examples/mineru_to_kg/` | `runner_cli.py` | 类似，进度来自 LangExtract 的 chunk 进度 + KG 构建子阶段 |

**为什么用 fd 3 而不是 stdout**：subprocess 的 stdout/stderr 留给原始日志（写入 `data/documents/{doc_id}/logs/`），fd 3 专门走结构化进度，避免日志混杂导致进度行被误解析。

#### 进度事件 schema（subprocess → worker）

每行一个 JSON：

```json
{"type": "progress", "stage": "parsing", "pct": 35, "detail": "MinerU state=running"}
{"type": "stage_done", "stage": "parsing", "elapsed_ms": 18500}
{"type": "error", "stage": "extracting", "message": "..."}
```

worker 把这些事件**透传**给 SSE 客户端，同时持久化到 `tasks.events_json`。

#### 失败处理

- subprocess 非零退出 → 读 stderr 日志 → 写 `error_message` → 状态 `failed` → push error 事件
- 文档已生成的部分文件**保留**（便于排查），但 status=failed 不出现在 ready 列表
- 任意阶段超时（默认 mineru 30 分钟、langextract 30 分钟，可在 .env 调）→ kill subprocess → 状态 failed
- `failed` 文档可调用 `POST /api/documents/{id}/retry` 重试（**MVP 不实现**，仅预留状态机支持）

### 4.2 进度事件总线（EventBus）

```python
class EventBus:
    """每个 task_id 对应一个 asyncio.Queue。
    SSE 端点订阅；worker 发布；任务终态后清理 Queue。"""
    
    def publish(task_id: str, event: dict) -> None: ...
    async def subscribe(task_id: str) -> AsyncIterator[dict]: ...
    def replay(task_id: str, last_event_id: str | None) -> list[dict]: ...
```

- 进程内单例，**不引入 Redis**（MVP 单机足够）
- 任务终态（complete/error）后 Queue 推 sentinel → SSE 端点收到后关闭连接
- 历史事件存 `tasks.events_json`；新订阅者先收到所有历史事件再接实时流（保证不漏）

### 4.3 Agent 缓存（AgentRunner）

```python
class AgentRunner:
    """KG + Agent 实例的 LRU 缓存（按 document_id）"""
    
    def get_or_load(document_id: str) -> tuple[KGStore, CompiledGraph]:
        # 命中 → 直接返回（O(ms)）
        # 未命中 → 加载 KG JSON → 构建 KGStore + agent → 缓存
    
    def cache_set(document_id, store, agent): ...   # 索引完成时主动塞入
    def evict(document_id): ...                      # 文档删除时主动清理
```

- LRU 大小 16（可配，按服务器内存定）
- 每个 KG 加载 ~50ms（实测 17 实体），可承受冷启动
- 文档刚 `ready` 时 worker **预加载**到缓存（用户首问时无冷启动延迟）

### 4.4 多轮会话上下文拼接

`POST /api/sessions/{id}/messages` 处理流程：

```python
async def handle_message(session_id, user_content, stream):
    session = sessions.get(session_id)
    history = messages.list_by_session(session_id, limit=20)  # 截取最后 20 条
    
    msgs = [{"role": m.role, "content": m.content} for m in history]
    msgs.append({"role": "user", "content": user_content})
    
    store, agent = agent_runner.get_or_load(session.document_id)
    
    if stream:
        async for event in agent.astream({"messages": msgs}):
            yield format_sse(event)
    else:
        result = await agent.ainvoke({"messages": msgs})
        return format_response(result)
    
    # 落库
    messages.insert(session_id, "user", user_content)
    messages.insert(session_id, "assistant", answer, tool_calls=...)
    sessions.update_count(session_id, +2)
```

**注意点**：
- 历史消息无限增长会超 LLM 上下文；MVP 截最后 20 条（约 10 轮）
- `tool_calls` 和 `tool_results` 也是历史的一部分，否则 Agent 不知道之前调用过什么工具
- 流式接口需把 LangGraph 的 `astream` 事件映射到 §3.4 定义的 SSE 事件类型

### 4.5 部署考虑（MVP 范围内）

- **单进程**：`uvicorn` 单 worker（多 worker 会让 EventBus / Agent 缓存出问题）
- **持久化目录**：`data/` 必须挂载到稳定磁盘
- **配置**：所有可调参数走 `.env`（端口、并发任务数、LRU 大小、超时、日志级别）
- **日志**：标准 `logging`，模块级 logger，开发模式 INFO，生产 WARNING
- **MVP 不做**：Docker / k8s / 多副本 / 鉴权 / 限流 / 监控（这些是后续工程化议题）

---

## 5. 项目结构与启动

### 5.1 目录结构

```
graphrag_backend/                    # ★ 新增组件
├── .env                             # 后端配置（端口 / 数据目录 / 复用 Qwen Key）
├── .gitignore
├── pyproject.toml                   # 依赖 + 通过 [tool.uv.sources] 引入 graphrag_pipeline
├── .venv/                           # 与 graphrag_pipeline 共用 venv
├── README.md
├── app/
│   ├── main.py                      # FastAPI 应用入口
│   ├── deps.py                      # 依赖注入（DB session / EventBus / AgentRunner）
│   ├── config.py                    # 配置加载（.env）
│   ├── routers/
│   │   ├── documents.py
│   │   ├── tasks.py
│   │   ├── sessions.py
│   │   └── health.py
│   ├── schemas/                     # Pydantic 模型
│   │   ├── document.py
│   │   ├── task.py
│   │   ├── session.py
│   │   └── error.py
│   ├── store/
│   │   ├── db.py                    # SQLite 连接 / 迁移
│   │   ├── models.py                # SQLAlchemy ORM
│   │   └── files.py                 # 文档目录布局工具
│   ├── orchestrator/
│   │   ├── job.py                   # IndexJob：subprocess 串联 + 进度
│   │   ├── runner.py                # 后台 worker 池
│   │   └── progress.py              # subprocess 进度行解析
│   ├── agent_runner/
│   │   └── cache.py                 # KGStore + Agent 的 LRU 缓存
│   ├── events/
│   │   └── bus.py                   # EventBus（asyncio.Queue per task）
│   └── sse.py                       # SSE 响应工具
├── data/                            # 运行时数据（gitignore）
│   ├── index.db
│   └── documents/
└── tests/                           # 简单的端到端测试

# 旁路新增（在已有组件内）
mineru_mvp/runner_cli.py             # ★ 新增：subprocess 入口
langextract_src/examples/mineru_to_kg/runner_cli.py  # ★ 新增：subprocess 入口
```

### 5.2 启动方式

```bash
cd /home/xukai/yixun/projects/graphragAgent

# 启动后端服务
uv run --project graphrag_backend uvicorn app.main:app --host 0.0.0.0 --port 8000

# 开发模式（自动 reload）
uv run --project graphrag_backend uvicorn app.main:app --reload --port 8000
```

环境隔离规则同其他组件：进入项目根用 `--project` 锁定 venv；与 mineru_mvp / langextract_src 跨 venv 通过 subprocess。

### 5.3 配置项（`.env`）

```bash
# 服务
HOST=0.0.0.0
PORT=8000
DATA_DIR=./data

# 复用 Qwen 配置（与 graphrag_pipeline 一致）
QWEN_API_KEY=sk-...
QWEN_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_LLM_MODEL=qwen3.7-max

# 跨 venv subprocess 路径（启动时探活）
MINERU_VENV_PYTHON=../mineru_mvp/.venv/bin/python
LANGEXTRACT_VENV_PYTHON=../langextract_src/.venv/bin/python

# 任务编排
MAX_CONCURRENT_INDEX_JOBS=2          # 同时索引几个文档
MINERU_TIMEOUT_SECONDS=1800          # 30 分钟
LANGEXTRACT_TIMEOUT_SECONDS=1800
AGENT_LRU_SIZE=16                    # Agent 缓存大小
SESSION_HISTORY_LIMIT=20             # 多轮上下文最多取多少条

# 日志
LOG_LEVEL=INFO
```

---

## 6. MVP 范围与后续扩展点

### 6.1 MVP 实现范围

✅ **必须实现**：
- 13 个 API 端点（按 §3 规范）
- SQLite 4 张表（documents / tasks / sessions / messages）
- 文档自包含目录布局
- subprocess + 进度事件（mineru / langextract 各加一个 runner_cli.py）
- EventBus 进程内单例
- AgentRunner LRU 缓存
- 多轮会话上下文拼接
- 健康检查 + 启动期探活

### 6.2 显式不做（后续扩展点）

| 功能 | 后续怎么加 |
| --- | --- |
| 鉴权 / 限流 | FastAPI middleware 加在 routers 前 |
| 跨文档查询 | 新增 `POST /api/sessions` 支持 `document_ids: list[str]`，AgentRunner 合并多 KG |
| 增量索引（追加文档） | 当前模型已支持，无需改 schema |
| 失败任务重试 | `POST /api/documents/{id}/retry` 端点 + 状态机已预留 |
| 完整对话持久化 | messages 表已支持，加分页查询接口即可 |
| 流式 token 推送的工程化 | 当前用 LangGraph `astream`，后续接入 LangSmith 监控 |
| Docker 部署 | 标准 Dockerfile，data/ 挂载卷 |
| 多副本 | 把 EventBus 换成 Redis pub/sub；任务编排换成 Celery |

### 6.3 验收标准

| 维度 | 标准 |
| --- | --- |
| 端到端跑通 | 上传 PDF → 索引完成 → 创建会话 → 提问 → 收到带溯源回答 |
| SSE 进度 | 索引过程中每个阶段都有事件推送，前端能展示进度条 |
| 多轮上下文 | 第二个问题"Q4 呢？"能正确理解为基于上一轮的延续 |
| 文档隔离 | 删除 A 文档不影响 B 文档；A 的会话级联删除 |
| 重启不丢 | 服务重启后任务状态可恢复（events_json 还在）；正在跑的任务标记为 failed |
| 性能 | 单文档索引（5 页）< 60s；问答首 token 延迟 < 3s（实测 graphrag_pipeline 已能做到） |

---

## 7. 信息来源

- 前置规范：`docs/mineru_specification-v1.0.md`、`docs/langextract_specification-v1.0.md`、`docs/index_pipeline_specification-v1.0.md`、`docs/agentic_rag_mvp_specification-v1.0.md`
- 现有实现：`mineru_mvp/`、`langextract_src/examples/mineru_to_kg/`、`graphrag_pipeline/`
- 环境隔离规范：`AGENTS.md`、`.kiro/steering/environment-isolation.md`
- LangChain 文档：https://docs.langchain.com/oss/python/langgraph/agentic-rag（via MCP）
- 头脑风暴决策：本规范 v1.0 关键设计决策表（架构 / 进度 / 存储 / 作用域 / 会话）

> 本规范是设计文档，落地实现完成后将补充「⚠️ 实测校准」章节，与项目其他 v1.0 规范风格保持一致。

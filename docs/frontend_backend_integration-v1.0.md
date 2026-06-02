# 前后端接口对接说明 v1.0

记录前端 (`frontend/`) 接入后端 (`backend/`) 真实 API 的实现细节、字段映射、限制项。

## 1. 启动方式

```bash
# 后端（必须先起，监听 :8000）
cd backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

# 前端（dev 模式，监听 :5173，Vite 通过 proxy 转发 /api → :8000）
cd frontend
pnpm dev
```

生产部署可把 `frontend/dist/` 直接挂到 FastAPI `StaticFiles`，无需 proxy。

## 2. API 客户端结构

```
frontend/src/app/api/
├── client.ts   # apiFetch + ApiError + apiUrl
├── sse.ts      # openEventSource (GET) + postSse (POST)
├── types.ts    # wire 类型（与 backend/app/schemas 对齐）
└── index.ts    # 高层 API + wire→UI 适配器
```

`App.tsx` 仅依赖 `./api`，不再 import `mockData`。

## 3. 字段映射

| 后端 wire | 前端 UI | 备注 |
| --- | --- | --- |
| `document_id` | `Document.id` | |
| `original_filename` | `Document.name` | |
| `created_at` (ms) | `Document.uploadedAt` (Date) | |
| `kg_stats.entity_count / triple_count` | `Document.kg.{entities, relations}` | |
| `current_task.progress_pct` | `Document.progress` | |
| `session_id / document_id / title / created_at` | `Session.{id, documentId, name, createdAt}` | |
| `MessageWire.tool_calls[]` | `Message.toolCalls[].name` (status 默认 `done`) | |
| `MessageWire.latency_ms / 1000` | `Message.elapsed` | |
| `KGDocument.entities[]` | `KGData.nodes[]` | label/entityClass/properties 透传 |
| `KGDocument.triples[]` | `KGData.edges[]` 或落到 subject 的 properties | 见 §4 |

## 4. KG 适配规则

后端 `triples` 形态有 3 种：
- `{value}`：纯字面量 → 折叠到 subject 节点的 `properties[predicate]`
- `{value, unit}`：字面量+单位 → 同上，拼成 `"value unit"`
- `{value, unit, metric_id}`：指向具体 metric 实体 → 生成 `subject → metric_id` 的边

虚拟主语（如 `_group_Q1`）在实体表中没有，但 `metadata.group_label` 提供了显示标签。适配器自动补一个 `Group` 节点。

实测：`17 entities + 34 triples → 22 UI nodes (含 5 个 group) + 15 边`，无悬挂边。

## 5. SSE 事件

### 索引进度（GET `/api/tasks/{id}/events`）

后端事件名：`stage_start | progress | stage_done | complete | error`

后端 `progress.pct` 是**总进度 0–99**（按 parsing 40% / extracting 50% / building_kg 10% 加权）。前端用 `STAGE_BASE / STAGE_WEIGHT` 还原成每个 stage 的局部 0–100 喂给 `IndexProgress`。

### 流式问答（POST `/api/sessions/{id}/messages`，stream=true）

后端事件名：`tool_call | token | complete | error`。

前端 `streamChat()` 用 `fetch + ReadableStream` 解析，按帧（`\n\n` 分隔）分发到回调。

## 6. 错误规范

后端所有 4xx/5xx 返回：
```json
{ "detail": { "code": "DOCUMENT_NOT_READY", "message": "文档尚未就绪" } }
```

前端 `apiFetch` 抛 `ApiError(status, code, message, detail)`，UI 层根据 code 走分支或直接展示 message。

## 7. 当前未对接的能力（标记为"未开发"）

| UI 能力 | 状态 | 说明 |
| --- | --- | --- |
| 消息溯源 chips（`Message.sources`） | 未开发 | 后端 agent 不返回 entity_id+location，前端不展示溯源块 |
| 命中节点高亮 | 简化版 | 后端不返回命中实体，前端取 KG 前 3 个节点高亮 2.5s（仅视觉提示） |
| 重试 | 局部限制 | 失败重试会重发 user 消息，后端会再次入库一条重复用户消息 |
| 刷新页面后恢复进度订阅 | 部分实现 | 仍在索引中的文档显示 active 占位，但不会真正订阅 task_id（需后端把 task_id 暴露在 `GET /api/documents/{id}` 顶层） |
| 健康检查面板 | 仅顶栏指示灯 | TopBar 仅看 `status === 'ok'`；详细 checks 未展示 |

## 8. 已知限制（不在本次对接范围）

- 后端 `health.status=degraded` 是因为 mineru/langextract 子组件 venv 路径相对当前 `backend/.env`（如 `../mineru_mvp/.venv/bin/python`）解析不到。修正 `MINERU_VENV_PYTHON` / `LANGEXTRACT_VENV_PYTHON` 为绝对路径或调整启动 cwd 即可。
- 流式问答会返回 `LLM_ERROR: graphrag_pipeline 未安装` 直到 `graphrag_pipeline` 被 `[tool.uv.sources]` 装入 `backend/.venv`。不影响其他 12 个端点。

## 9. 集成测试结果

后端在 `:8000` 启动后，前端构建产物 `pnpm build` 编译通过；`/api/documents`、`/api/documents/{id}`、`/api/documents/{id}/kg`、`/api/tasks/{id}/events`、`/api/sessions`、`/api/sessions/{id}` 全部字段对齐通过；KG 适配器 22 节点/15 边，所有边引用合法节点。

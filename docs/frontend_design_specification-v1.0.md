# GraphRAG 前端设计规范 v1.0

本规范定义多模态 RAG 问答系统的前端页面设计、交互逻辑与视觉风格，作为前端实现的契约。

**前置规范**：
- `docs/graphrag_backend_specification-v1.0.md`（后端 API 接口契约）
- `docs/agentic_rag_mvp_specification-v1.0.md`（问答返回数据格式）
- `docs/index_pipeline_specification-v1.0.md`（KG 数据结构）

**关键设计决策**（头脑风暴阶段已确认）：

| 决策 | 选择 |
| --- | --- |
| 布局 | 三区布局（左文档库 · 中问答 · 右知识图谱） |
| 视觉风格 | 深色精密（OKLCH 冷蓝中性色，高对比低噪声） |
| 响应式策略 | 桌面三区 → 平板折叠图谱 → 移动端双栏 |
| 技术栈 | 单页应用（SPA），纯 HTML + vanilla JS + D3.js（无框架） |
| 进度推送 | SSE（EventSource） |
| 问答流式 | SSE 逐 token 推送 |

---

## 1. 页面清单

整个系统是**单页应用**，通过状态切换展示不同视图，无路由跳转。

| 视图 | 触发条件 | 核心内容 |
| --- | --- | --- |
| **空状态** | 无文档时 | 居中上传引导 |
| **文档列表 + 上传进度** | 有文档但未选中 / 正在上传 | 左栏文档列表 + 中栏进度面板 |
| **问答主视图** | 选中一个 ready 文档 | 三区完整展示 |
| **上传弹层** | 点击"上传"按钮 | 拖拽区 + 文件选择（overlay，非 modal） |

---

## 2. 三区布局规范

### 2.1 桌面（≥1200px）

```
┌─────────────────────────────────────────────────────────────┐
│ TopBar (44px)                                                │
├──────────┬──────────────────────────────┬───────────────────┤
│ 左栏      │ 中栏                          │ 右栏              │
│ 220px    │ flex:1 (min 400px)           │ 420px             │
│ 文档库    │ 问答对话                      │ 知识图谱           │
│          │                              │                   │
│          │                              │                   │
└──────────┴──────────────────────────────┴───────────────────┘
```

- TopBar 固定 44px，含 Logo + 健康状态
- 左栏固定 220px，可折叠（点击 Logo 旁的 toggle）
- 中栏弹性伸缩，最小 400px
- 右栏固定 420px，可折叠（点击图谱标题旁的 toggle）

### 2.2 平板（768px–1199px）

- 右栏（知识图谱）折叠为**可展开面板**（从右侧滑入，覆盖中栏 60%）
- 中栏右上角出现"图谱"按钮，点击展开
- 左栏保持 180px

### 2.3 移动端（<768px）

- 左栏折叠为**底部 tab 或汉堡菜单**
- 中栏全屏
- 图谱入口在对话顶部 tab 切换

---

## 3. 视觉风格（深色精密）

### 3.1 色彩系统（OKLCH）

| 变量 | 值 | 用途 |
| --- | --- | --- |
| `--bg` | `oklch(0.12 0.008 260)` | 页面背景 |
| `--surface` | `oklch(0.16 0.01 260)` | 面板/卡片背景 |
| `--surface-2` | `oklch(0.19 0.01 260)` | 输入框/气泡背景 |
| `--surface-3` | `oklch(0.22 0.01 260)` | hover/active 状态 |
| `--border` | `oklch(0.26 0.01 260)` | 分割线 |
| `--text` | `oklch(0.92 0.005 260)` | 主文本 |
| `--text-2` | `oklch(0.65 0.008 260)` | 次要文本 |
| `--text-3` | `oklch(0.42 0.008 260)` | 辅助/标签文本 |
| `--accent` | `oklch(0.65 0.18 200)` | 主色（青蓝） |
| `--accent-dim` | `oklch(0.45 0.12 200)` | 主色暗调 |
| `--green` | `oklch(0.65 0.16 155)` | 成功/就绪 |
| `--amber` | `oklch(0.72 0.16 80)` | 进行中/警告 |
| `--red` | `oklch(0.62 0.18 25)` | 失败/错误 |
| `--purple` | `oklch(0.65 0.16 300)` | 辅助色 |

### 3.2 排版

- 字体：`-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif`
- 基础字号：13px
- 行高：1.55
- 标题层级：通过 weight（600/700）+ size（11px/13px/15px）区分，不用大字号
- 代码/entity_id：`"SF Mono", "Cascadia Code", monospace`，11px

### 3.3 圆角与间距

- 面板圆角：0（贴边）
- 卡片/气泡：8–10px
- 按钮：5–7px
- 输入框：8px
- 间距节奏：4 / 8 / 12 / 16 / 24（不用 20）

### 3.4 图谱节点配色

| entity_class | 节点颜色 |
| --- | --- |
| metric | `oklch(0.65 0.18 200)` 青蓝 |
| organization | `oklch(0.65 0.16 155)` 绿 |
| duration | `oklch(0.65 0.16 80)` 琥珀 |
| person | `oklch(0.65 0.16 340)` 粉紫 |
| disease | `oklch(0.62 0.18 25)` 红 |
| drug | `oklch(0.65 0.16 120)` 青绿 |
| publication | `oklch(0.65 0.16 300)` 紫 |
| cohort | `oklch(0.6 0.14 45)` 暖橙 |
| group（虚拟节点） | `oklch(0.45 0.08 260)` 灰 |

---

## 4. 交互逻辑

### 4.1 文档上传流程

```
用户点击"+ 上传" → 弹出拖拽区 overlay
  → 选择/拖入文件
  → POST /api/documents（multipart）
  → 立即返回 {document_id, task_id, events_url}
  → 关闭 overlay
  → 左栏新增文档条目（status=pending）
  → 自动连接 SSE events_url
  → 中栏切换为"索引进度"视图
  → SSE 事件驱动进度条 + 阶段文字更新
  → complete 事件 → 文档状态变 ready → 自动进入问答视图
```

### 4.2 索引进度展示

中栏在文档未 ready 时展示进度面板：

- 三阶段进度条（parsing → extracting → building_kg）
- 当前阶段高亮 + 百分比
- 已完成阶段打勾 + 耗时
- 失败时：红色错误信息 + 重试按钮（预留）

SSE 事件映射：
- `stage_start` → 切换当前阶段高亮
- `progress` → 更新百分比 + detail 文字
- `stage_done` → 该阶段打勾 + 显示耗时
- `complete` → 进度面板消失，切换到问答视图
- `error` → 显示错误信息

### 4.3 问答交互

```
用户输入问题 → 按回车或点击发送
  → 中栏追加 user 气泡
  → POST /api/sessions/{id}/messages（stream=true）
  → 建立 SSE 连接
  → tool_call 事件 → 显示工具调用标签（如 ⚡ find_metrics）
  → tool_result 事件 → 标签变为已完成状态
  → token 事件 → 逐字追加到 assistant 气泡
  → complete 事件 → 气泡定型 + 显示来源引用 + 耗时
  → 右栏图谱：高亮本次查询涉及的节点（从 tool_calls.args 提取 entity_id）
```

### 4.4 知识图谱交互

- **默认**：展示当前文档的完整 KG（`GET /api/documents/{id}/kg`）
- **问答联动**：每次 assistant 回答后，高亮涉及的节点（放大 + 发光效果，2s 后恢复）
- **点击节点**：弹出 tooltip 展示 entity 详情（label / properties / sources）
- **拖拽**：D3 force drag
- **缩放**：滚轮 zoom
- **图例**：底部固定，按 entity_class 着色

### 4.5 会话管理

- 中栏顶部 tab 切换不同会话
- "新会话"按钮创建新 session（`POST /api/sessions`）
- 切换会话时加载历史消息（`GET /api/sessions/{id}/messages`）
- 删除会话：tab 右键菜单或长按

### 4.6 文档管理

- 左栏文档列表按 `updated_at` 降序
- 点击文档 → 切换到该文档的问答视图
- 右键/长按 → 删除（确认弹窗）
- 状态 pill：就绪（绿）/ 解析中（琥珀 + 百分比）/ 失败（红）

---

## 5. 组件清单

| 组件 | 位置 | 职责 |
| --- | --- | --- |
| `TopBar` | 顶部 | Logo + 健康状态 + 全局操作 |
| `Sidebar` | 左栏 | 文档列表 + 上传按钮 + 统计 |
| `DocItem` | 左栏内 | 单个文档条目（名称 + 状态 pill + KG 统计） |
| `UploadOverlay` | 覆盖层 | 拖拽上传区 |
| `IndexProgress` | 中栏 | 三阶段进度条 + SSE 驱动 |
| `ChatPanel` | 中栏 | 会话 tab + 消息列表 + 输入框 |
| `MessageBubble` | 中栏内 | 单条消息（user/assistant 两种样式） |
| `ToolCallTag` | 气泡内 | 工具调用标签（名称 + 参数摘要） |
| `SourceRef` | 气泡下方 | 来源引用（entity_id + document_id + char_interval） |
| `KGPanel` | 右栏 | 图谱容器 + 图例 + 统计 |
| `ForceGraph` | 右栏内 | D3.js 力导向图（节点 + 边 + 交互） |
| `NodeTooltip` | 右栏浮层 | 节点详情弹出 |

---

## 6. API 调用映射

| 前端动作 | 后端 API | 响应处理 |
| --- | --- | --- |
| 页面加载 | `GET /api/documents` | 渲染左栏文档列表 |
| 上传文件 | `POST /api/documents` | 拿 task_id → 连 SSE |
| 监听索引进度 | `GET /api/tasks/{id}/events`（SSE） | 驱动进度条 |
| 选中文档 | `GET /api/documents/{id}/kg` | 渲染右栏图谱 |
| 创建会话 | `POST /api/sessions` | 拿 session_id |
| 列出会话 | `GET /api/sessions?document_id=` | 渲染 tab |
| 发送问题 | `POST /api/sessions/{id}/messages`（SSE） | 逐 token 渲染 |
| 加载历史 | `GET /api/sessions/{id}/messages` | 渲染历史气泡 |
| 删除文档 | `DELETE /api/documents/{id}` | 移除左栏条目 |
| 删除会话 | `DELETE /api/sessions/{id}` | 移除 tab |
| 健康检查 | `GET /api/health` | TopBar 状态点 |

---

## 7. 响应式断点

| 断点 | 布局变化 |
| --- | --- |
| ≥1200px | 三区完整展示（220 + flex + 420） |
| 768–1199px | 右栏折叠为滑入面板；左栏缩窄至 180px |
| <768px | 左栏变底部 tab；中栏全屏；图谱为顶部 tab 切换 |

---

## 8. 技术实现约束

- **无框架**：纯 HTML + CSS + vanilla JS（与现有 `static/index.html` 一致）
- **D3.js**：CDN 引入 v7（知识图谱力导向图）
- **SSE**：原生 `EventSource` API
- **Markdown 渲染**：assistant 回答中的 `**bold**` / `\n` 用简单正则转 HTML（不引入 marked.js）
- **构建工具**：无（单文件或少量文件直接 serve）
- **部署**：FastAPI `StaticFiles` 挂载 `static/` 目录

---

## 9. 动效规范

| 场景 | 动效 | 参数 |
| --- | --- | --- |
| 面板折叠/展开 | width transition | 200ms ease-out-quart |
| 气泡出现 | opacity + translateY | 150ms ease-out |
| 进度条推进 | width transition | 400ms ease-out |
| 图谱节点高亮 | r 放大 + glow filter | 300ms ease-out，2s 后恢复 |
| 工具调用标签出现 | opacity + scale | 120ms ease-out |
| 上传 overlay | opacity + backdrop-filter | 200ms |
| 状态 pill 变化 | background-color transition | 300ms |

所有动效使用 `ease-out-quart`（`cubic-bezier(0.25, 1, 0.5, 1)`），不用 bounce/elastic。

---

## 10. 空状态与边界情况

| 场景 | 展示 |
| --- | --- |
| 无文档 | 中栏居中：上传引导图标 + "上传第一个文档开始" |
| 文档 ready 但无会话 | 中栏：欢迎消息 + 建议问题（基于 KG stats 生成） |
| 问答中 LLM 超时 | 气泡显示错误提示 + "重试"按钮 |
| 图谱为空（0 实体） | 右栏居中："暂无图谱数据" |
| SSE 断线 | 自动重连（3 次，间隔 2/4/8s）；失败后显示"连接中断"提示 |
| 文件类型不支持 | 上传时前端校验 + toast 提示 |
| 文件超 200MB | 上传时前端校验 + toast 提示 |

---

## 11. 信息来源

- 后端 API 契约：`docs/graphrag_backend_specification-v1.0.md`
- 问答返回格式：`docs/agentic_rag_mvp_specification-v1.0.md` 第 5 节
- KG 数据结构：`docs/index_pipeline_specification-v1.0.md` 第 5 节
- 视觉原型：`.superpowers/brainstorm/1459357-1780206736/content/full-prototype.html`
- 头脑风暴决策：三区布局 + 深色精密 + 响应式折叠策略

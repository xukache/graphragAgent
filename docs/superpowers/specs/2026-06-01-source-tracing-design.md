# 来源溯源功能设计 v1.0

**日期**：2026-06-01  
**范围**：在现有三区布局基础上，为 assistant 消息的来源 chip 增加两个联动行为：点击 → KG 节点高亮 + 原文抽屉展示。

---

## 1. 背景与目标

### 现状

- `Message.sources` 类型已定义（`entityId / documentId / location / text`），但 `toUiMessage` 里写死 `sources: undefined`，来源块从不渲染。
- `KGNode.sources` 字段已在类型定义中，但 `toKGData` 没有把实体的 `sources[]` 传入。
- 来源 chip UI 已写好（静态文字行），但无点击交互。
- KG 高亮机制已有（`setHighlightedIds`），未与来源联动。

### 目标

点击 assistant 消息下方的来源 chip，同时触发：
1. 右侧 KG 图谱高亮对应节点
2. 中栏右侧滑入原文抽屉，展示该实体所在页面的完整文本，命中区间高亮

---

## 2. 数据流设计

### 2.1 新增后端接口

**`GET /api/documents/{document_id}/pages`**

- 读取 `data/documents/{id}/mineru/*content_list.json`
- 按 `page_idx` 分组，拼接每页所有块的文本：
  - `text` 块：直接取 `text` 字段
  - `table` 块：取 `table_body`，去除 HTML 标签保留纯文本
- 返回格式：
  ```json
  { "pages": { "source.pdf_page_0": "第0页完整文本...", "source.pdf_page_1": "..." } }
  ```
- 文档不存在 → 404
- mineru 产物不存在（老文档）→ 返回 `{ "pages": {} }`，不报错

### 2.2 前端数据链路

```
选中 ready 文档
  → 并行请求：getKG(docId) + getDocumentPages(docId)
  → kgByDoc[docId]       = KGData（含 KGNode.sources）
  → pageTextByDoc[docId] = Record<pageId, string>

complete 事件（回答完成）
  → entity_ids 列表
  → 从 currentKg.nodes 查找每个 entity_id 的 sources[]
  → 组装 Message.sources = [{entityId, documentId, charInterval, label, entityClass}]
```

### 2.3 `toKGData` 补充

把实体的 `sources[]` 传入 `KGNode.sources`：

```typescript
nodeMap.set(e.entity_id, {
  id: e.entity_id,
  label: e.label,
  entityClass: e.entity_class || 'Default',
  properties: stringifyProps(e.properties),
  sources: (e.sources ?? []).map(s => ({
    entityId: e.entity_id,
    documentId: s.document_id,
    charInterval: s.char_interval ?? null,
    alignmentStatus: s.alignment_status ?? null,
  })),
});
```

### 2.4 `Message.sources` 组装（App.tsx `onComplete`）

```typescript
// entity_ids 来自 complete 事件
const sources = entityIds.flatMap(eid => {
  const node = currentKg?.nodes.find(n => n.id === eid);
  if (!node) return [];
  return (node.sources ?? []).map(s => ({
    entityId: eid,
    documentId: s.documentId,
    location: s.documentId,   // 页面 ID，如 "source.pdf_page_0"
    text: node.label,         // 实体标签作为摘要文本
    charInterval: s.charInterval,
    entityLabel: node.label,
    entityClass: node.entityClass,
  }));
});
```

---

## 3. 交互设计

### 3.1 来源 chip（改造现有 UI）

现有静态行改为可点击 chip：

```
[ ⬡ Haoyu Han · person · source.pdf_page_0 ]
```

- 悬停：背景加深（`oklch(0.22 0.01 260)`）+ cursor pointer
- 点击：触发 `onSourceClick(source)` 回调，传出完整 source 对象
- 无 `charInterval`（对齐失败）：chip 仍可点击，抽屉降级展示全页文本

### 3.2 原文抽屉（新组件 `SourceDrawer`）

从中栏右侧滑入，覆盖聊天区域约 50%，不影响 KG 面板：

```
┌──────────┬──────────────────────────────┬───────────────────┐
│ Sidebar  │ ChatPanel（被遮住一半）        │ KGPanel           │
│          │         ┌────────────────────┤                   │
│          │         │ SourceDrawer       │                   │
│          │         │ ─────────────────  │                   │
│          │         │ 📄 source.pdf      │                   │
│          │         │ 第 0 页            │                   │
│          │         │                    │                   │
│          │         │ ...前文...          │                   │
│          │         │ ██命中文本██        │                   │
│          │         │ ...后文...          │                   │
│          │         │                    │                   │
│          │         │ [×] 关闭           │                   │
│          │         └────────────────────┤                   │
└──────────┴──────────────────────────────┴───────────────────┘
```

**抽屉内容**：
- 顶部：文档名 + 页码（`source.pdf_page_0` → "第 0 页"）+ 关闭按钮（×）
- 实体标签：entity_class 颜色圆点 + label（如 `● person · Haoyu Han`）
- 正文区：该页完整文本，命中 `char_interval` 区间用黄色高亮背景标出，自动滚动到命中位置
- 底部：`entity_id` monospace 小字

**动效**：`translateX(100%)` → `translateX(0)`，200ms `cubic-bezier(0.25, 1, 0.5, 1)`，与现有面板折叠动效一致。

**关闭方式**：
- 点击关闭按钮（×）
- 点击抽屉外部区域（遮罩层）
- 按 Esc 键

### 3.3 点击来源 chip 的完整事件链

```
用户点击 chip
  → App.tsx: setHighlightedIds([entityId])          // KG 节点高亮（4s 后自动消退）
  → App.tsx: setDrawerSource({                       // 打开抽屉
               entityId, pageId, charInterval,
               entityLabel, entityClass, docId
             })
  → SourceDrawer: 从 pageTextByDoc[docId][pageId]
                  取文本，按 charInterval 切三段
                  [前文][高亮背景][后文] 渲染
                  自动滚动到高亮位置
```

---

## 4. 降级处理

| 场景 | 行为 |
|---|---|
| `pageTextByDoc` 未加载完 | 抽屉显示 loading 骨架 |
| `char_interval` 为 null（对齐失败） | 显示页面全文，不高亮，顶部提示"无法定位原文位置" |
| mineru 产物不存在（老文档） | 抽屉显示"原文暂不可用（文档需重新索引）" |
| entity 在 KG 中无 sources | chip 不渲染（不展示无法溯源的来源） |

---

## 5. 变更清单

### 后端（1 处新增）

| 文件 | 变更 |
|---|---|
| `backend/app/routers/documents.py` | 新增 `GET /{document_id}/pages` 路由 |

### 前端（5 处改动 + 1 个新组件）

| 文件 | 变更 |
|---|---|
| `frontend/src/app/api/types.ts` | 新增 `DocumentPagesWire` 类型 |
| `frontend/src/app/api/index.ts` | `toKGData` 补充 `KGNode.sources`；新增 `getDocumentPages()` |
| `frontend/src/app/types.ts` | `Source` 扩展 `charInterval` + `entityLabel` + `entityClass` 字段 |
| `frontend/src/app/App.tsx` | 新增 `pageTextByDoc` state；选中文档时并行拉 pages；`onComplete` 组装 `Message.sources`；新增 `drawerSource` state；`onSourceClick` 回调 |
| `frontend/src/app/components/ChatPanel.tsx` | 来源 chip 改为可点击，新增 `onSourceClick` prop |
| `frontend/src/app/components/SourceDrawer.tsx` | 新组件：原文抽屉 |

---

## 6. 不在本次范围内

- 文档原文的全文搜索
- 多个来源同时高亮（每次只高亮最后点击的一个）
- 移动端适配（抽屉在小屏幕上的布局）
- 来源 chip 的"复制 entity_id"功能

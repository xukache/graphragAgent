# 来源溯源功能实现计划 v1.0

**日期**：2026-06-01
**设计文档**：`docs/superpowers/specs/2026-06-01-source-tracing-design.md`
**目标**：把"点击来源 chip → 节点高亮 + 原文抽屉"按 11 个可独立验证的任务落地，最小化串行依赖。

---

## 0. 总览

| 项 | 数值 |
|---|---|
| 任务总数 | 11（后端 2 / 前端类型层 2 / 前端 UI 5 / 集成验证 2） |
| 预估新增代码 | 后端 ~80 行 / 前端 ~350 行 |
| 关键依赖 | `data/documents/{id}/mineru/*content_list.json`（后端读取，前端无感） |
| 回归风险点 | `Message.sources` 字段类型扩展（影响 `toUiMessage`）、App.tsx 状态增多 |

---

## 1. 任务分解

> 编号 = 建议执行顺序。前置依赖见每张卡的 **依赖** 字段。

### 后端（可独立于前端先做）

- **T1** — 新增 `GET /api/documents/{id}/pages` 路由与 Pydantic schema
- **T2** — 后端 API 烟测：404 / 200 / 产物缺失 三种情况

### 前端类型层（依赖 T1 的 schema 形态，但只读 wire 字段名，可并行）

- **T3** — `api/types.ts` 新增 `DocumentPagesWire`
- **T4** — `api/index.ts` 补 `toKGData.sources` 映射 + 新增 `getDocumentPages()`

### 前端 UI 层（依赖 T3/T4）

- **T5** — `types.ts` 扩展 `Source` 字段（`charInterval` / `entityLabel` / `entityClass`）
- **T6** — `App.tsx` 新增 `pageTextByDoc` + `drawerSource` state，并行拉取、清理、`onComplete` 组装 `sources`
- **T7** — 新建 `components/SourceDrawer.tsx`
- **T8** — `ChatPanel.tsx` 来源 chip 改造（`onSourceClick` prop + 交互态）
- **T9** — `App.tsx` 集成 `SourceDrawer`（挂在中心面板上，z-index 高于 ChatPanel）

### 集成验证

- **T10** — 端到端浏览器验证：选文档 → 提问 → 点 chip → 抽屉 + 高亮
- **T11** — 降级场景回归：`char_interval` 为 null / 老文档无 mineru / 关闭后再开

---

## 2. 依赖图

```
T1 ──→ T2                 (后端独立闭环)
T1 ──→ T3 ──→ T4          (类型层)
T4 ──→ T5 ──→ T6 ──→ T8 ──→ T9 ──→ T10 ──→ T11
                ↓
                T7 ─────────────↗
```

- T1 → T3：T3 的 `DocumentPagesWire` 字段名需对齐 T1 的 Pydantic schema
- T4 → T5：T5 的 `Source` 字段名需对齐 T4 的 `toKGData` 输出
- T6 → T7：T6 把 `pageTextByDoc` 传给 T7，但 T7 写时可先 mock
- T8 → T9：T8 暴露 `onSourceClick` 后 T9 才能在 App.tsx 串联

---

## 3. 详细任务卡

---

### T1 · 后端 `pages` 路由

**文件**：
- 新增：`backend/app/schemas/document.py` 加 `DocumentPagesOut`
- 修改：`backend/app/store/files.py` 加 `content_list_path(doc_id)` 辅助
- 修改：`backend/app/routers/documents.py` 加 `GET /{document_id}/pages`

**Schema**：
```python
class DocumentPagesOut(BaseModel):
    pages: dict[str, str]  # page_id -> 拼接后的纯文本
```

**路由行为**：
1. 查 `documents` 表，无 → `404 DOCUMENT_NOT_FOUND`
2. 查 `documents/{id}/mineru/*content_list.json`（glob 一个）
   - 不存在 → 返回 `{"pages": {}}`（200，不报错）
3. 解析 JSON 数组，按 `page_idx` 分组
4. 拼接规则：
   - `type == "text"` → 取 `text` 字段，`"\n"` 分隔
   - `type == "table"` → 取 `table_body`，用正则 `re.sub(r"<[^>]+>", "", html)` 去 HTML 标签，`"\n"` 分隔
   - 其他类型（image / equation / …）→ 跳过
5. page_id 格式：`f"{document_id}_page_{page_idx}"`（用文档 UUID + 页码，与设计 §2.1 示例的 "source.pdf_page_0" 格式不同，按用户确认改用 document_id）
6. 排序：按 `page_idx` 升序

**依赖**：无

**验收**：
- 单元测试：见 T2
- 单文件代码 ≤ 60 行

---

### T2 · 后端 API 烟测

**文件**：`backend/tests/test_api.py` 末尾追加 4 个测试函数

**测试点**：
1. `test_pages_not_found`：`GET /api/documents/不存在/pages` → 404
2. `test_pages_no_mineru`：上传 fake PDF → 等 0.5s → 调 `/pages` → 200 + `{"pages": {}}`
3. `test_pages_with_mineru`：手工往 `data/documents/{id}/mineru/` 写一个最小 content_list.json（3 块、2 页）→ 调 `/pages` → 验证拼接文本、page_id 格式
4. `test_pages_table_block`：写一个含 `type=table` + `<table><tr><td>` 的块 → 验证 HTML 标签被去除

**依赖**：T1

**验收**：
- `python -m pytest backend/tests/test_api.py -k pages` 全绿
- 现有 13 个测试不退化

---

### T3 · 新增 `DocumentPagesWire`

**文件**：`frontend/src/app/api/types.ts`

**代码**：
```typescript
export interface DocumentPagesWire {
  pages: Record<string, string>;  // page_id -> text
}
```

**依赖**：T1（确认字段名）

**验收**：
- TypeScript 编译通过
- 与 `api/index.ts` 的 `getDocumentPages` 返回类型一致

---

### T4 · `toKGData` 补 `sources` + `getDocumentPages()`

**文件**：`frontend/src/app/api/index.ts`

**改动 1**：`toKGData` 在 `nodeMap.set(e.entity_id, {...})` 里追加 `sources`
```typescript
sources: (e.sources ?? []).map((s) => ({
  documentId: s.document_id,
  charInterval: s.char_interval ?? null,
  alignmentStatus: s.alignment_status ?? null,
})),
```

**改动 2**：文件末尾新增
```typescript
export async function getDocumentPages(documentId: string): Promise<Record<string, string>> {
  const w = await apiFetch<DocumentPagesWire>(`/api/documents/${documentId}/pages`);
  return w.pages;
}
```

**依赖**：T3

**验收**：
- TS 编译通过
- 现有 `getKG` 行为不退化（对比一份样例 KG JSON 的实体数 / 边数）

---

### T5 · 扩展 `Source` 字段

**文件**：`frontend/src/app/types.ts`

**改动**：
```typescript
export interface Source {
  entityId: string;
  documentId: string;
  location: string;        // page_id
  text: string;            // 摘要（实体 label）
  charInterval: { start_pos: number; end_pos: number } | null;
  entityLabel: string;
  entityClass: string;
}
```

**依赖**：T4

**验收**：TS 编译通过；旧使用方（`toUiMessage.sources: undefined`）继续兼容

---

### T6 · `App.tsx` 状态与数据流

**文件**：`frontend/src/app/App.tsx`

**新增 state**：
```typescript
const [pageTextByDoc, setPageTextByDoc] = useState<Record<string, Record<string, string>>>({});
const [drawerSource, setDrawerSource] = useState<DrawerSource | null>(null);

interface DrawerSource {
  entityId: string;
  entityLabel: string;
  entityClass: string;
  pageId: string;
  charInterval: { start_pos: number; end_pos: number } | null;
}
```

**新增 effect**：选中文档变化时，在原 `useEffect([selectedDocId, documents])` 内 `Promise.all` 加 `getDocumentPages`
```typescript
const [kg, pages] = await Promise.all([
  getKG(selectedDocId),
  getDocumentPages(selectedDocId).catch(() => ({})),
]);
setKgByDoc((prev) => ({ ...prev, [selectedDocId]: kg }));
setPageTextByDoc((prev) => ({ ...prev, [selectedDocId]: pages }));
```

**删除文档时清理**：`handleDeleteDoc` 加 `setPageTextByDoc((prev) => { delete prev[docId]; return prev; })`

**`onComplete` 组装 `sources`**：
```typescript
const sources: Source[] = (entityIds ?? []).flatMap((eid) => {
  const node = currentKg?.nodes.find((n) => n.id === eid);
  if (!node) return [];
  return (node.sources ?? []).map((s) => ({
    entityId: eid,
    documentId: s.documentId,
    location: s.pageIdForChip(s.documentId),  // 见下方辅助
    text: node.label,
    charInterval: s.charInterval,
    entityLabel: node.label,
    entityClass: node.entityClass,
  }));
});
```

> 实际写法：把 `s.documentId` 当作 `page_id`（与设计 §2.1 一致），location 直接取该值。如后端 page_id 与 `documentId` 不同，需在 T4 改用 `s.pageId` 字段。

**依赖**：T5

**验收**：
- TS 编译通过
- 手动跑：选文档 → 提问 → 浏览器 Network 面板可见 `/pages` 请求
- 切回老文档（无 mineru 产物）不报错，`pageTextByDoc[oldId] === {}`

---

### T7 · `SourceDrawer` 组件

**文件**：新建 `frontend/src/app/components/SourceDrawer.tsx`

**Props**：
```typescript
interface SourceDrawerProps {
  source: DrawerSource | null;            // null = 关闭
  pageText: string;                       // 该页完整文本
  documentName: string;
  onClose: () => void;
}
```

**实现要点**：
- `position: absolute`，`right: 0; top: 0; bottom: 0; width: 50%`（中栏内的右半部分）
- 200ms `cubic-bezier(0.25, 1, 0.5, 1)` translateX 动画
- `Escape` 键监听：`useEffect` 加 `keydown` 监听器
- 文本切片：
  - 无 `charInterval` → 直接显示全文
  - 有 → `[text.slice(0, start)][<mark>text.slice(start, end)</mark>][text.slice(end)]`
  - 渲染后用 `useEffect` 滚到 `<mark>` 元素
- HTML 转义：复用 `ChatPanel.escapeHtml`（先抽到 `ui/escapeHtml.ts` 再 import，避免循环依赖）
- 视觉：
  - 头部：📄 文档名 + "第 N 页" + 关闭 ×
  - 实体行：entity_class 圆点（颜色从 KGPanel 的 `CLASS_COLORS` 抄）+ label
  - 正文区：white-space: pre-wrap; line-height: 1.6
  - mark 样式：`background: oklch(0.72 0.16 80 / 0.35); border-radius: 2px;`
  - 底部：entity_id monospace 小字

**依赖**：T6（用其 `DrawerSource` 类型），但 T7 可先用本地接口写，import 时再对齐

**验收**：
- TS 编译通过
- 组件能独立用 Storybook-like 方式渲染（App.tsx 集成前）

---

### T8 · `ChatPanel` 来源 chip 改造

**文件**：`frontend/src/app/components/ChatPanel.tsx`

**改动 1**：props 加 `onSourceClick?: (src: Source) => void`

**改动 2**：`MessageBubble` 来源 div 改为可点击 button
```typescript
{msg.sources.map((src, i) => (
  <button
    key={i}
    onClick={() => onSourceClick?.(src)}
    onMouseEnter={(e) => (e.currentTarget.style.background = 'oklch(0.22 0.01 260)')}
    onMouseLeave={(e) => (e.currentTarget.style.background = 'oklch(0.16 0.01 260)')}
    style={{
      background: 'oklch(0.16 0.01 260)',
      border: 'none',
      borderLeft: '2px solid oklch(0.65 0.18 200 / 0.5)',
      borderRadius: '0 4px 4px 0',
      padding: '4px 8px',
      fontSize: 10,
      color: 'oklch(0.55 0.008 260)',
      fontFamily: 'SF Mono, Cascadia Code, monospace',
      cursor: 'pointer',
      textAlign: 'left',
    }}
  >
    <span style={{ color: 'oklch(0.65 0.18 200 / 0.7)' }}>⬡ {src.entityLabel}</span>
    {' · '}
    <span style={{ color: 'oklch(0.42 0.008 260)' }}>{src.entityClass}</span>
    {' · '}
    <span style={{ color: 'oklch(0.42 0.008 260)' }}>{src.location}</span>
  </button>
))}
```

**依赖**：T5

**验收**：
- TS 编译通过
- 旧 props（无 `onSourceClick`）不报错

---

### T9 · `App.tsx` 集成 `SourceDrawer`

**文件**：`frontend/src/app/App.tsx`

**新增 handler**：
```typescript
const handleSourceClick = useCallback((src: Source) => {
  // 1) 高亮节点（4s 后消退，与现有 onComplete 行为一致）
  setHighlightedIds([src.entityId]);
  setTimeout(() => setHighlightedIds((prev) => prev.filter((id) => id !== src.entityId)), 4000);
  // 2) 打开抽屉
  setDrawerSource({
    entityId: src.entityId,
    entityLabel: src.entityLabel,
    entityClass: src.entityClass,
    pageId: src.location,  // documentId 直接当作 page_id
    charInterval: src.charInterval,
  });
}, []);
```

**新增渲染**（在中心面板 div 内，ChatPanel 之后）：
```typescript
{selectedDocId && pageTextByDoc[selectedDocId] && (
  <SourceDrawer
    source={drawerSource}
    pageText={
      drawerSource
        ? pageTextByDoc[selectedDocId]?.[drawerSource.pageId] ?? ''
        : ''
    }
    documentName={selectedDoc?.name ?? ''}
    onClose={() => setDrawerSource(null)}
  />
)}
```

**props 透传**：`ChatPanel` 加 `onSourceClick={handleSourceClick}`

**依赖**：T7 + T8

**验收**：
- TS 编译通过
- 抽屉层级正确：覆盖 ChatPanel 右半部分，不影响 KGPanel

---

### T10 · 端到端浏览器验证

**前置**：dev server + 后端在跑，库里至少一份 ready 文档带 mineru 产物

**测试脚本**（人工执行）：
1. 选中文档（ready）→ 确认 Network 多了 `/pages` 请求
2. 等 KG 加载完（KGPanel 显示节点）
3. 提问"列出文档里的人名"→ 等 streaming 完成
4. 验证：
   - assistant 消息下出现 chip：`⬡ Haoyu Han · person · source.pdf_page_0`
   - KGPanel 自动聚焦到该节点（4s 高亮）
   - 点击 chip → 中栏右半滑入抽屉，显示该页文本，命中区间黄色高亮
   - 抽屉自动滚动到命中位置
5. 再点另一个 chip → 抽屉内容更新，KG 节点高亮更新

**通过标准**：上述 5 步全过

**依赖**：T9

---

### T11 · 降级场景回归

**场景 1**：`char_interval` 为 null
- 选一个 entity 触发，但该 entity 在 KG 的 `sources[].char_interval` 为 null
- 期望：chip 仍可点击，抽屉显示页面全文，顶部提示"无法定位原文位置"

**场景 2**：老文档无 mineru 产物
- `data/documents/{id}/mineru/` 不存在
- 期望：抽屉显示"原文暂不可用（文档需重新索引）"

**场景 3**：entity 在 KG 中无 sources
- 后端 `entity_ids` 包含某 ID，但该节点的 `sources` 数组为空
- 期望：`Message.sources` 不包含该 entity（chip 不渲染）

**场景 4**：抽屉关闭后状态清理
- 点击 × 关闭抽屉
- 再点 chip → 抽屉重新打开，无残留状态

**通过标准**：4 个场景表现与设计 §4 一致

**依赖**：T10

---

## 4. 验收方法汇总

| 任务 | 验收手段 | 通过标准 |
|---|---|---|
| T1 | 代码评审 + 单元测试 | 4 个测试函数全过；schema 与 Pydantic 兼容 |
| T2 | `pytest backend/tests/test_api.py` | 全部 17 个测试全过 |
| T3 | `tsc --noEmit` | 0 错误 |
| T4 | `tsc --noEmit` + KG JSON diff | 实体数 / 边数不变；sources 字段非空 |
| T5 | `tsc --noEmit` | 0 错误 |
| T6 | `tsc --noEmit` + 浏览器 Network 面板 | `/pages` 请求在选中文档时触发 |
| T7 | `tsc --noEmit` + Storybook-like 独立渲染 | 组件无运行时错误 |
| T8 | `tsc --noEmit` + 视觉确认 | chip 悬停变深、cursor pointer |
| T9 | `tsc --noEmit` + T10 | drawer z-index 正确，不被 KGPanel 遮挡 |
| T10 | 人工端到端 | 5 步全过 |
| T11 | 人工降级测试 | 4 场景表现与设计一致 |

---

## 5. 风险与降级

| 风险 | 缓解 |
|---|---|
| `page_id` 格式与 KG 端 `char_interval.start_pos` 的偏移基准不一致（mineru 的 `start_pos` 是全文字符级，page_id 是页级） | 后端只在 `pages` 字典里给文本，不掺对齐；前端用 `char_interval` 直接对 page 文本做字符切片。若切片越界（T11 场景 1），前端降级到全文 + 提示。 |
| T6 改了 `toKGData`，可能让 `toUiMessage` 旧 mock 数据缺字段 | T5 把所有新字段都标为可选或 null，老 mock 不会炸 |
| 抽屉 width: 50% 在窄屏（< 800px）会挤掉输入框 | 不在本次范围（设计 §6 明示），但 T7 写时加 `min-width: 480px` 防止过度挤压 |
| `pages` 接口慢（大文档几十页） | 选中文档 effect 已有 try/catch；前端在 `pages` 加载完前抽屉显示 loading 骨架 |
| 旧 `toUiMessage` 注释 `// sources 暂未由后端返回` 现在不准确 | T6 完成后删除该注释 |

---

## 6. 任务 → 设计追溯

| 设计章节 | 对应任务 |
|---|---|
| §2.1 后端 `pages` 接口 | T1, T2 |
| §2.2 数据链路 | T3, T4, T6 |
| §2.3 `toKGData` 补充 | T4 |
| §2.4 `Message.sources` 组装 | T6 |
| §3.1 来源 chip 改造 | T8 |
| §3.2 原文抽屉 | T7, T9 |
| §3.3 点击事件链 | T9 |
| §4 降级处理 | T7（loading/HTML fallback），T11（验证） |
| §5 变更清单 | 全部任务 |

---

## 7. 实施顺序建议

1. **Day 1 上午**：T1（后端路由）+ T2（烟测）→ 提交
2. **Day 1 下午**：T3 + T4（类型层）→ 提交
3. **Day 2 上午**：T5 + T6（状态与数据流）→ 提交
4. **Day 2 下午**：T7（Drawer 组件）→ 提交
5. **Day 3 上午**：T8 + T9（chip 改造 + 集成）→ 提交
6. **Day 3 下午**：T10 + T11（端到端 + 降级）→ 提交

总工作量：约 1.5 人天。

---

## 8. Commit 分组（6 组）

| Commit | 任务 | 内容 | 验收命令 |
|---|---|---|---|
| C1 | T1 + T2 | 后端 `pages` 路由 + 4 个 pytest | `pytest backend/tests/test_api.py -k pages` |
| C2 | T3 + T4 | 前端 wire 类型 + `getDocumentPages()` + `toKGData.sources` | `cd frontend && npx tsc --noEmit` |
| C3 | T5 + T6 | `Source` 扩展 + App state + `onComplete` 组装 | `tsc --noEmit` + 浏览器 Network 看到 `/pages` |
| C4 | T7 | `SourceDrawer` 组件 | `tsc --noEmit` |
| C5 | T8 + T9 | ChatPanel chip 改造 + App 集成 | `tsc --noEmit` + 视觉确认 |
| C6 | T10 + T11 | 端到端 + 降级场景 | 人工清单（见 T10/T11） |

## 9. 不在本次范围

与设计 §6 一致，复述：
- 文档原文的全文搜索
- 多个来源同时高亮
- 移动端适配
- 来源 chip 的"复制 entity_id"功能

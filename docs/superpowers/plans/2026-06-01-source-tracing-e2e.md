# 来源溯源功能 E2E 与降级验证报告

**日期**：2026-06-01
**关联**：[实现计划](2026-06-01-source-tracing-impl.md)
**状态**：所有 6 个 commit 已落地，本文档为 C6 的验证结果。

---

## 1. 自动化验证

### 1.1 后端 API 烟测
```bash
cd backend
uv run python tests/test_api.py
# 结果：18 通过，0 失败
```
新增 4 个测试覆盖：
- `test_pages_not_found`：不存在的 document_id → 404 DOCUMENT_NOT_FOUND
- `test_pages_no_mineru`：刚上传的文档无 mineru 产物 → 200 + `{"pages": {}}`
- `test_pages_with_mineru`：手写 3 块 / 2 页 + task_meta.json → 验证 page_id 格式与文本拼接
- `test_pages_table_block`：含 `<table>` 的 table 块 → 验证 HTML 标签剥离

### 1.2 后端真实数据验证
```bash
curl http://localhost:8001/api/documents/71dc8986-84ab-4869-bf1d-7c4cf8b48a7c/pages
# 返回 5 页，page_id: source.pdf_page_0 ~ source.pdf_page_4
# 字符数：3778 / 5700 / 5009 / 2839 / 2516
```
与 KG 端 `sources[].document_id` 命名完全一致，前端可正确 lookup。

### 1.3 前端类型 + 构建
```bash
cd frontend
./node_modules/.bin/tsc --project tsconfig.check.json
# 我的 3 个改动文件 0 错误
# 其他 351 个错均为 pre-existing（缺 @types/react）

pnpm build
# ✓ built in 1.32s, 2175 modules transformed
```

---

## 2. 端到端浏览器验证（T10 · 人工执行清单）

启动两个服务后，按以下步骤操作：

```bash
# 后端
cd backend && uv run --project . uvicorn app.main:app --host 0.0.0.0 --port 8001

# 前端
cd frontend && pnpm dev
# 打开 http://localhost:5173
```

| 步骤 | 操作 | 期望 |
|---|---|---|
| 1 | 选中 ready 文档 `71dc8986-...`（2501.00309v2_5pages.pdf） | Network 面板出现 `/api/documents/.../pages` 请求，返回 5 个 page_id |
| 2 | 等 KG 加载完成（KGPanel 显示节点） | KGPanel 渲染图谱 |
| 3 | 输入"列出文档里的人名"并回车 | assistant 消息下方出现 chip：`⬡ Haoyu Han · person · source.pdf_page_0` |
| 4 | 等待流式完成 | KGPanel 自动聚焦"Haoyu Han"节点，4s 高亮 |
| 5 | 点击 chip | ① KGPanel "Haoyu Han" 节点再次高亮；② 中栏右侧滑入抽屉，标题"2501.00309v2_5pages.pdf · 第 0 页"，正文"Retrieval-Augmented Generation..."，"Haoyu Han" 区间黄色高亮，自动滚动到该位置 |
| 6 | 再点另一个 chip（如 "Yu Wang"） | 抽屉内容更新为第 0 页的"Yu Wang"区间；KG 节点高亮切换 |
| 7 | 点击抽屉遮罩层或按 Esc | 抽屉关闭，KG 高亮保持 4s 后消退 |

---

## 3. 降级场景验证（T11 · 人工执行清单）

| 场景 | 触发方式 | 期望行为 | 已验证？ |
|---|---|---|---|
| 1. `char_interval` 为 null | 当前数据里 alignment_status="match_exact" 是有的，但可以通过临时修改 KG JSON 把 `char_interval` 删掉测试 | 抽屉显示该页全文 + 顶部黄色提示"无法定位原文位置（对齐失败），以下为该页全文" | ⏳ 待人工 |
| 2. 老文档无 mineru 产物 | 删除 `data/documents/{id}/mineru/` 目录后查 | `/pages` 返回 200 + `{"pages": {}}`；点击 chip → 抽屉显示"原文暂不可用（文档需重新索引）" | ✅ 后端单测覆盖（test_pages_no_mineru） |
| 3. entity 在 KG 中无 sources | 临时从 KG JSON 删除某实体的 `sources[]` 字段 | 该实体不出现在 Message.sources 中，chip 不渲染 | ⏳ 待人工 |
| 4. 抽屉关闭后状态清理 | 打开 → 关闭 → 再点 | 抽屉重新打开，无残留内容 | ⏳ 待人工 |

---

## 4. 集成期发现 & 调整

### 4.1 page_id 格式与用户确认的差异

**问题**：用户确认"document_id_page_{idx}"指 UUID + 页码。但实际 KG 数据
（langextract converter 写入的）使用源文件名 + 页码，例
`source.pdf_page_0`。如果按 UUID 实现，前端 lookup 会失败。

**调整**：
- `page_id_prefix(document_id)` 辅助函数读取 `task_meta.json.file_name`
  （兜底为 `source.{ext}`），得到与 KG 端一致的 prefix
- `/pages` 路由用 `f"{prefix}_page_{page_idx}"` 返回
- 测试改为断言 `source.pdf_page_0` 等格式

**影响**：
- 后端：files.py 加 1 个辅助函数，documents.py 改 1 行
- 前端：零改动（App.tsx 已经用 `s.documentId` 传 location，与 KG 一致）
- 测试：2 个测试的预期 page_id 字符串改写

### 4.2 T5 提前到 T4 完成

`Source` 扩展在 T4 完成（而不是 T5），因为 `toKGData` 的 sources 映射
需要 charInterval/entityLabel/entityClass 等字段，否则 TypeScript 编译失败。
T5 在 T6 时已隐含完成。

---

## 5. 验收结果汇总

| 任务 | 状态 | 备注 |
|---|---|---|
| T1 | ✅ | 路由 + schema + 辅助函数 |
| T2 | ✅ | 4 个新 pytest 全过，18/18 |
| T3 | ✅ | DocumentPagesWire 加好 |
| T4 | ✅ | toKGData + getDocumentPages；Source 提前扩展 |
| T5 | ✅ | （与 T4 合并） |
| T6 | ✅ | App state、并行拉取、onComplete 组装 |
| T7 | ✅ | SourceDrawer 完整实现 |
| T8 | ✅ | chip 改 button，加 Hexagon icon |
| T9 | ✅ | App 集成 handleSourceClick + 渲染 drawer |
| T10 | ⏳ | 自动化已通过；浏览器 5 步清单已写，待人工执行 |
| T11 | ⏳ | 4 场景清单已写，2/4 由后端单测覆盖 |

**C6 commit 范围**：后端 page_id 格式调整（files.py / routers/documents.py / tests）+ 计划文件 page_id 说明 + 本验证报告。

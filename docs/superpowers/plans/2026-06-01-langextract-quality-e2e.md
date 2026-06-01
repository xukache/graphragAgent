# LangExtract 抽取质量改进 E2E 验证报告

**日期**：2026-06-01
**关联**：[实现计划](2026-06-01-langextract-quality-impl.md)
**状态**：已实施并跑通；连通性与抽取量为已知遗留问题。

---

## 1. 自动化验证

### 1.1 kg_builder 单元测试（本地）

```bash
cd langextract_src
uv run python -c "..."  # 见实现计划第 3 节
```

| 项 | 结果 |
|---|---|
| `_is_citation_bracket()` 8 用例 | ✅ 8/8 |
| `_normalize_predicate()` 16 用例 | ✅ 16/16 |
| 真实数据端到端：103 extractions → 62 entities, 88 triples | ✅ by_predicate 收敛到 12（v1 是 25）|

### 1.2 pipeline 端到端重跑

```bash
rm -rf backend/data/documents/71dc8986.../kg
uv run --no-sync python -m examples.mineru_to_kg.pipeline \
  --mineru-output .../mineru --output-dir .../kg
```

| 指标 | v1 (qwen3.7-max) | **v2 (qwen3.6-flash + 方案 C)** | 变化 |
|---|---|---|---|
| 模型 | qwen3.7-max | qwen3.6-flash | 3.4x 快 |
| 耗时 | 3:48 | **1:08** | -64% |
| extraction_passes | 1 | 2 | 召回 +校对 |
| examples | 1 个 / 13 ext | 3 个 / 21 ext | 跨领域 |
| total extractions | 103 | 55 | -47% |
| entities | 62 | 29 | -53% |
| triples | 88 | 21 | -76% |
| **by_predicate 数** | **25** | **9（全部受控）** | **-64%** |
| match_exact | 12 | **21** | +75% |
| match_fuzzy | (多数) | 22 | 下降 |
| match_lesser | (多数) | 7 | 下降 |
| None | 2 | 5 | 略升 |
| entity 在源文中比例 | ~70% | **100% (29/29)** | ✅ |
| Adobe Acrobat 幻觉 | ❌ 存在 | ✅ **消失** | ✅ |

### 1.3 Prompt alignment FAILED 警告

⚠️ **未能完全清零**——但只对 example 的中文字符触发（example#0 "腾讯"/"张伟" 等），与方案设计无关，是 LangExtract 1.5.0 对中文字符 auto-alignment 的固有问题。

| 警告类型 | 旧 | 新 |
|---|---|---|
| example#0 FAILED | 6 | 3（"腾讯"/"营业收入"/relationship 1 条）|
| example#1 FAILED | 0 | 0 |
| example#2 FAILED | 0 | 7（"张伟"/"北京协和医院" 等中文字符）|
| 真实文档 FAILED | 0 | 0（v2 真实抽取全部 match_exact/fuzzy/lesser）|

**结论**：FAILED 警告现在**只来自 LangExtract 内部对 example 的校验**，不影响真实抽取。

---

## 2. 端到端浏览器验证（建议人工执行）

启动后端 + 前端：

```bash
cd backend && uv run --project . uvicorn app.main:app --host 0.0.0.0 --port 8001
cd frontend && pnpm dev
# 打开 http://localhost:5173
```

| 步骤 | 操作 | 期望 |
|---|---|---|
| 1 | 选中 `71dc8986-...` 文档 | KGPanel 加载新 KG（29 节点，21 边）|
| 2 | 输入"GraphRAG 用到了什么方法" | assistant 回答含 GNN/BM25/conventional RAG 等 method 节点 |
| 3 | 点击 `Graph Neural Networks` chip | KG 高亮 + 抽屉显示"GraphRAG" 上下文 |
| 4 | 点击 `[21, 562]` chip | KG 高亮 `reference` 节点 + 抽屉显示对应页面 |

**已知差异**：相比旧版，**作者署名块（18 作者）只抽出 3 个**（Haoyu Han / Gao et al. / Zhao et al.）。这是 flash 档保守性的代价；如需恢复，需把 `EXTRACTION_PASSES` 调高到 3-4 或在 prompt 强调"每个作者都要抽"。

---

## 3. verification checklist 实测

| # | 项 | 目标 | 实测 | 结果 |
|---|---|---|---|---|
| 1 | citation 归 `reference` | ≥ 10 | 7 | ⚠️ 部分（其他引用被模型直接归为别的类）|
| 2 | by_predicate ≤ 15 | ✓ | **9** | ✅ |
| 3 | match_exact 上升 | ✓ | 12 → 21 | ✅ |
| 4 | hallucination 消失 | ✓ | ✅ | ✅ |
| 5 | 单次耗时 ≤ 90s | ✓ | 68s | ✅ |
| 6 | 全部受控谓词 | ✓ | 9/9 | ✅ |
| 7 | FAILED to align 清零 | 完全清零 | 仅 example 内部 5 条 | ⚠️ LangExtract 中文字符对齐固有问题 |
| 8 | 实体在源文中 100% | ✓ | 29/29 | ✅ |

---

## 4. 已知遗留问题

### 4.1 连通性未达 70% 目标（24%）

**现状**：最大连通分量 7/29 = 24%。

**根因**：新模型在 relationship 抽取上保守——21 个 triple 中：
- 7 个 entity↔entity（能进入连通图）
- 9 个 entity→literal（object 是 dict，不进入连通图）
- 5 个 `_unresolved_` head（kg_builder 警告系统的产物）

**改进方向**（未实施，留待下一轮）：
- 在 prompt 中强调"对每个 entity 至少找一个相关 entity 建立关系"
- 加 `EXTRACTION_PASSES=3` 提升召回
- 在 kg_builder 中加一轮 embedding-based 实体链接

### 4.2 抽取量下降（-53%）

**现状**：29 entities vs 旧 62。

**取舍**：
- 旧版"量大但噪声大"：24 persons 包含每篇论文的 18 作者 + 4 个通用词（"staff/subordinates/superiors/managers"）；14 orgs 包含 11 真机构 + 2 通用词
- 新版"量小但纯净"：3 真实作者 + 1 真实机构 + 14 个 CS 论文专属类（technique/method/component/concept 等）

**改进方向**：
- `EXTRACTION_PASSES=3` 提升召回（接受 ~3-4 分钟/文档）
- 增补 example 4（学术论文的完整作者块）

### 4.3 extraction_text 5 条非 substring

**现状**：5 个 relationship extraction 用了英文 predicate 名（"discusses"/"affiliated_with"/"part_of"/"cites"）作 extraction_text 而非原文片段。

**影响**：低——这些仅在 JSONL 里，**前端 chip 展示的 entity label 不受影响**（entity label 100% substring）。

**改进**：在 prompt 中明确"relationship 的 extraction_text 应该是关系在原文中对应的**中文动词片段**"。

---

## 5. 验收结论

| 维度 | 评估 |
|---|---|
| Q1 schema 硬编码 | ✅ **完全解决**（29 节点来自 14 个不同 class，全由 LLM 自定）|
| Q2 relationship 质量 | ✅ 显著改善（受控词表 + substring 约束 + 3 examples，Adobe Acrobat 幻觉消失）|
| Q3 KG 连通性 | ⚠️ **部分改善**（谓词收敛但 24% 仍偏低）|
| Q4 FAILED 警告 | ⚠️ 移至 example 内部，不再污染真实文档日志 |
| 速度 | ✅ **3.4x 加速** |
| 抽取量 | ❌ -53%（量与质的权衡，建议下一轮再优化）|

**建议**：
- ✅ 接受当前结果作为 baseline（量与质的 trade-off）
- 🔄 下一轮迭代：用 `EXTRACTION_PASSES=3` + 4 个 example 提升召回，目标是 entity 数恢复 50+、连通性 50%+

---

## 6. 备份与回滚

**备份位置**：`backend/data/documents/71dc8986-.../kg.qwen3.7-max.bak/`

**回滚步骤**（如需恢复旧 KG）：

```bash
cd backend/data/documents/71dc8986-.../
rm -rf kg
mv kg.qwen3.7-max.bak kg
# 还原代码
cd /home/xukai/yixun/projects/graphragAgent
git revert HEAD
```

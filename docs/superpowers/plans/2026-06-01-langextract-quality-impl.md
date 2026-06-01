# LangExtract 抽取质量改进实现计划 v1.0

**日期**：2026-06-01
**目标**：修复 4 个 LangExtract Stage 2 质量问题——schema 硬编码、relationship 混杂/编造、KG 聚簇小、alignment FAILED 警告。
**方案**：候选 C（开放 entity schema + 受控 relation vocabulary + substring 硬约束）
**关联调研**：本次对话 Step 1-3 产出（README 中不再展开）

---

## 0. 总览

| 项 | 数值 |
|---|---|
| 改动文件 | 3 代码 + 2 文档 + 1 计划文件 |
| 预估新增代码 | ~150 行（prompts.py 重写）/ ~50 行（kg_builder.py 新增）/ ~20 行（pipeline.py 强化）|
| 关键依赖 | DashScope `qwen3.6-flash` 端点可用性（用户指定模型）|
| 回归风险点 | `entity_class` 不再固定 9 类（前端 chip 显示需兼容新类名）|

---

## 1. 问题回顾

| # | 症状 | 根因 |
|---|---|---|
| Q1 | `extraction_class` 硬编码 9 个英文 | `prompts.py` 3 处锁死 + 1 个 example |
| Q2 | relationship 少/中英混杂/编造 | example 1 个 + 自造 phrase + 无 substring 约束 |
| Q3 | KG 聚簇小、连通性差 | 跨页无合并 + citation bracket 当 entity + 25 个稀疏 predicate |
| Q4 | FAILED to align 警告 | example#0 自身 alignment 失败 |

**根因**（Q5）：这套 schema 是为"中文临床医学"设计的，现在套到 CS 综述（GraphRAG 论文）→ 领域/任务假设错配。

---

## 2. 方案 C：开放 entity + 受控 relation + substring 约束

3 处治理：entity 自由 / relation 收敛 / 抽取规则硬约束。

### 2.1 `prompts.py`（重写）

**PROMPT 改写**：
- 去掉 9 类枚举
- 改为"先决定 3-8 个适合本文的 entity class"
- 强制 10 个受控 relation 词表：`mentions / discusses / proposes / extends / evaluates / uses / affiliated_with / published_in / part_of / cites`
- 强制 `extraction_text` 必须是原文 substring

**build_examples() 改 3 个跨领域 example**：
| # | 主题 | entity class | relationship |
|---|---|---|---|
| 1 | 财务 | `company / period / metric` | `mentions` |
| 2 | 学术 | `author / institution / reference` | `affiliated_with / discusses` |
| 3 | 医学 | `researcher / institution / drug / disease / cohort / duration` | `uses / evaluates` |

3 个 example 的 21 个 extraction 全部满足 `extraction_text ∈ text`（substring 合规），从而让 LangExtract 的 auto-alignment 全部走 `match_exact`，清零 FAILED 警告。

### 2.2 `pipeline.py`（3 处强化）

```python
# 模型分档（默认 flash 档，extraction 无需 max）
TIER_TO_MODEL = {"max": "qwen3.7-max", "plus": "qwen-plus", "flash": "qwen3.6-flash"}
EXTRACTION_PASSES = 2       # 多 pass 提升召回
MAX_CHAR_BUFFER = 8000      # 避免长文被切碎
```

`load_config()` 优先级：`QWEN_LLM_MODEL` 显式 > `LX_MODEL_TIER` 映射 > 默认 `flash`。

### 2.3 `kg_builder.py`（2 处新增）

**Citation 归 reference 类**（不丢弃）：
```python
_CITATION_BRACKET_RE = re.compile(r"^\s*\[[\d\s,]+\]\s*$")
def _is_citation_bracket(label): ...
def _relabel_citations(entities): ...  # → "reference" 类，properties.auto_classified="citation_bracket"
```

**Predicate 归一化**：
- `CONTROLLED_PREDICATES`：10 个受控词 + 17 个 ATTR_TO_PREDICATE 内部词 + `has_value` = 27 个白名单
- `PREDICATE_ALIASES`：41 条映射（`treat/治疗 → evaluates`、`develops/operates → uses`、`任职于 → affiliated_with` 等）
- `_normalize_predicate()` 返回 `(归一后, 是否映射)`
- `generate_triples()` 出口处归一化，归一化的在 `metadata.predicate_normalized_from` 留痕
- 不在白名单也未命中别名 → 在 `metadata.warning="uncontrolled_predicate:xxx"` 标记

### 2.4 `.env` 不需改

`mineru_to_kg/.env` 已是 `QWEN_LLM_MODEL=qwen3.6-flash`（用户提前改好）。

---

## 3. 验证 checklist（实施后跑）

- [ ] `kg_builder.py` 单元自测：citation 归 `reference`、predicate 归一化生效
- [ ] 重跑后 `extracting.stderr.log` FAILED 警告**清零**
- [ ] 重跑后 by_class 中 `reference` ≥ 10 个、`publication` 显著下降
- [ ] by_predicate 字典长度 ≤ 15（25 → 大幅收敛）
- [ ] 最大连通分量 ≥ 70%
- [ ] spot-check 5 个 chip，extraction_text 全部能在 source 中精确匹配
- [ ] `Adobe develops Adobe Acrobat` hallucinated triple **不再出现**
- [ ] 单次抽取耗时 ≤ 90s（228s → flash 档目标 1 分钟内）

---

## 4. 风险与回滚

| 风险 | 触发条件 | 回滚动作 |
|---|---|---|
| `qwen3.6-flash` 不存在 | DashScope 返回 400/404 | `export QWEN_LLM_MODEL=qwen3.7-max` 重跑 |
| flash 档抽取质量差 | spot-check < 70% 通过 | 同上 |
| extraction_passes=2 触发限流 | DashScope 429 | 改 `EXTRACTION_PASSES=1` |
| prompt 改动破坏现有数据 | 跑出新 KG 实体数 < 30 | git revert + 用 `.bak` 恢复 |

**当前备份**：`backend/data/documents/71dc8986.../kg.qwen3.7-max.bak/`。

---

## 5. 改动文件清单

| 文件 | 性质 | 改动量 |
|---|---|---|
| `langextract_src/examples/mineru_to_kg/prompts.py` | 重写 | +120/-80 |
| `langextract_src/examples/mineru_to_kg/pipeline.py` | 强化 | +30/-10 |
| `langextract_src/examples/mineru_to_kg/kg_builder.py` | 新增 | +90/-5 |
| `langextract_src/examples/mineru_to_kg/.env` | 无需改 | 0（已正确）|
| `docs/langextract_specification-v1.0.md` | 更新 | 部分章节 |
| `docs/index_pipeline_specification-v1.0.md` | 更新 | 部分章节 |
| `docs/superpowers/plans/2026-06-01-langextract-quality-impl.md` | 新建 | 本文件 |

---

## 6. 关联文档

- 上游：调研 Step 1-3 上下文（本次对话内）
- 下游：实施后写 E2E 报告 `docs/superpowers/plans/2026-06-01-langextract-quality-e2e.md`

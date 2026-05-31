# Qwen MVP（阿里千问接入）

基于 `docs/langextract_pipeline_spec.md`，使用阿里千问（DashScope OpenAI-compatible 端点）作为后端 LLM，跑通最小化结构化抽取链路：

```
模拟文本输入 -> 千问 LLM 抽取 -> AnnotatedDocument -> JSONL + HTML 可视化
```

## 位置说明

本 MVP 直接放在 `langextract_src/examples/qwen_mvp/` 下，**复用 `langextract_src/.venv`**。这样：

- 与 langextract 自身依赖共用同一个虚拟环境，无须重复安装
- 与 Google 已有的 `examples/ollama/`、`examples/custom_provider_plugin/` 同级，符合项目惯例
- 业务/测试代码集中于 `langextract_src/`，避免外层目录冗余

## 文件

```
langextract_src/examples/qwen_mvp/
├── .env           # Qwen 配置（含 Key，已 gitignore）
├── .gitignore
├── pipeline.py    # 主 pipeline
├── README.md
└── output/        # 抽取结果（运行后生成）
```

## 运行（在 langextract_src/ 下执行）

```bash
cd langextract_src
uv run python examples/qwen_mvp/pipeline.py
```

依赖（`langextract`、`openai`、`python-dotenv`）已通过 `uv sync --all-extras` 装在 `langextract_src/.venv` 中，无须额外安装。

## 输出

- `output/extraction_results.jsonl`：标准 LangExtract JSONL（含 `char_interval`、`alignment_status`）
- `output/extractions_raw.json`：扁平化抽取明细（人类阅读友好）
- `output/visualization.html`：HTML 高亮可视化

## 关键实现说明

- **走 OpenAI provider 直连 Qwen**：通过 `ModelConfig(provider="OpenAILanguageModel", provider_kwargs={"base_url": ..., "api_key": ...})` 显式指定，绕过 `model_id` 自动路由（千问 model_id 不在 langextract 默认匹配模式中）。
- **代理清理**：DashScope 是国内域名，本机 SOCKS 代理会触发 SSL EOF；脚本启动时主动清理 `*_PROXY` 环境变量。
- **`use_schema_constraints=False`**：OpenAI-compatible 第三方端点对 structured output schema 兼容性参差，关闭更稳。
- **`fence_output=True`**：让模型用 ```` ```json ```` 包裹 JSON 输出，解析更稳。

## 模型切换

修改 `.env` 中的 `QWEN_LLM_MODEL` 即可。可选：`qwen-max`、`qwen-plus`、`qwen-turbo`、`qwen3-max` 等（DashScope 实际可用模型以官方文档为准）。

# MinerU MVP 测试

基于 `docs/mineru_parsing_spec.md`，使用 MinerU 精准解析 API（路径 B）实现的最小可运行 pipeline：

```
本地 PDF 加载 -> 云端 MinerU 解析 -> 本地解析结果存储
```

## 目录结构

```
mineru_mvp/
├── .env                 # 配置（含 Token，已 gitignore）
├── .gitignore
├── pyproject.toml       # 依赖声明（uv 统一用 pyproject.toml）
├── make_sample_pdf.py   # 生成测试用样例 PDF
├── mineru_pipeline.py   # 主 pipeline（上传 -> 轮询 -> 下载 -> 存储）
├── sample.pdf           # 生成的测试 PDF
├── .venv/               # uv 虚拟环境（gitignore）
└── output/              # 解析结果（运行后生成）
```

## 依赖安装

本组件使用独立的 `uv` 虚拟环境，与项目其他组件隔离：

```bash
cd mineru_mvp

# 初始化项目并同步依赖（自动创建 .venv 并安装 pyproject.toml 中声明的依赖）
uv sync

# 添加新依赖
uv add <package>

# 移除依赖
uv remove <package>
```

## 运行步骤

> ⚠️ 所有命令必须使用 `.venv` 内的 Python 解释器，禁止在系统环境或项目根环境中直接运行。

1. 生成样例 PDF：

   ```bash
   uv run python make_sample_pdf.py
   ```

2. 执行解析 pipeline（默认解析 `sample.pdf`）：

   ```bash
   uv run python mineru_pipeline.py
   # 或指定其他本地 PDF
   uv run python mineru_pipeline.py /path/to/your.pdf
   ```

   也可以先 activate 再运行：

   ```bash
   source .venv/bin/activate.fish   # fish shell
   # source .venv/bin/activate      # bash/zsh
   python mineru_pipeline.py
   ```

## 输出说明

运行后 `output/` 下包含：

- `result.zip`：MinerU 返回的原始结果压缩包
- `full.md`：Markdown 解析结果
- `*_content_list.json`：扁平内容列表（含 type / page_idx / bbox）
- `*_middle.json`：完整版面层级结构
- `*_model.json`：模型推理原始结果
- `*_layout.pdf` / `*_span.pdf`：可视化调试文件
- `images/`：图片/表格/公式截图
- `task_meta.json`：本次任务元数据

> 注意：MinerU 解析结果文件有效期 30 天，pipeline 已在完成后立即下载落盘。

## 关键实现说明

- 本地文件解析走批量上传接口 `POST /api/v4/file-urls/batch`（单文件 `extract/task` 仅支持 URL，不支持本地上传）。
- PUT 上传到 OSS 时不携带 `Authorization` / `Content-Type`，否则会触发签名校验失败。
- 轮询接口为 `GET /api/v4/extract-results/batch/{batch_id}`，直到 `state=done`。

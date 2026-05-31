# MinerU 文档解析规范文档

本文档基于 MinerU 官方 API 文档（https://mineru.net/apiManage/docs）与官方输出文件参考（https://opendatalab.github.io/MinerU/reference/output_files/）整理，用于指导本项目使用 MinerU 进行文档解析的 MVP 测试与后续工程化对接。

本项目采用 **🎯 精准解析 API（路径 B）**，因此本文档以路径 B 的输入输出规范为主线，重点说明：

1. 支持的原始输入文件格式
2. 路径 B 解析后的输出格式、最终生成文件清单及每个文件的详细字段说明
3. 解析后生成的布局信息，用于精准提取数值并对接 LangExtract 输入
4. 执行 MVP 的必要与必须字段

> 说明：MinerU 提供两套 API（🎯 精准解析 API 与 ⚡ Agent 轻量解析 API）。本文档聚焦路径 B（精准解析 API），仅在第 5 节附带两套对比，便于团队后续选型。

## 1. 支持的原始输入文件格式（路径 B）

精准解析 API 通过文件 URL 或本地文件上传两种方式接收原始文档，支持以下格式：

| 类别 | 支持的扩展名 | 说明 |
| --- | --- | --- |
| PDF | `.pdf` | 核心支持，支持扫描件（配合 OCR） |
| 图片 | `png` / `jpg` / `jpeg` / `jp2` / `webp` / `gif` / `bmp` | 单图解析 |
| Word | `.doc` / `.docx` | 后端转换后解析 |
| PPT | `.ppt` / `.pptx` | 后端转换后解析 |
| Excel | `.xls` / `.xlsx` | 后端转换后解析 |
| HTML | `.html` | 必须显式指定 `model_version="MinerU-HTML"`；非 HTML 文件使用 `pipeline` 或 `vlm` |

### 1.1 输入限制

| 限制项 | 限制值 |
| --- | --- |
| 单文件大小上限 | 200 MB |
| 单文件页数上限 | 200 页 |
| 批量单次申请上传链接 | ≤ 50 个 |
| 批量任务上限 | ≤ 200 个 |
| 每账号每日最高优先级额度 | 1000 页（超出部分优先级降低） |

### 1.2 输入提交方式

路径 B 有三种提交入口：

| 入口 | 接口 | 适用场景 |
| --- | --- | --- |
| 单文件 URL 解析 | `POST /api/v4/extract/task` | 已有公网可访问文件 URL |
| 本地文件批量上传 | `POST /api/v4/file-urls/batch` | 上传本地文件（先申请上传链接再 PUT 上传） |
| URL 批量解析 | `POST /api/v4/extract/task/batch` | 批量提交多个文件 URL |

输入注意事项：

- 文件名强烈建议带正确后缀名，否则可能触发错误码 `-60002`（获取匹配文件格式失败）。
- 因网络限制，GitHub、AWS 等海外 URL 会请求超时；优先使用国内可访问的 CDN/OSS URL。
- 本地文件上传时无须设置 `Content-Type` 请求头，上传完成后系统自动提交解析任务，无须再调用提交接口。
- 申请的文件上传链接有效期为 24 小时。
- 模型版本与文件类型的匹配规则：HTML 文件必须用 `MinerU-HTML`；非 HTML 文件可选 `pipeline`（默认）或 `vlm`（推荐）。

## 2. 路径 B 输出格式与生成文件规范

### 2.1 输出总览

精准解析 API 是异步接口，调用方需轮询任务状态，任务完成后通过 `full_zip_url` 下载结果压缩包。

- 单文件解析：轮询 `GET /api/v4/extract/task/{task_id}`，完成后返回 `full_zip_url`。
- 批量解析：轮询 `GET /api/v4/extract-results/batch/{batch_id}`，每个文件各自返回 `full_zip_url`。

输出形态：

| 输出维度 | 内容 |
| --- | --- |
| 顶层产物 | 一个 Zip 压缩包（`full_zip_url`） |
| 默认导出格式 | Markdown + JSON（无须设置） |
| 可选额外导出 | `extra_formats` 支持 `docx` / `html` / `latex` 中的一个或多个（对源文件为 HTML 的无效） |

### 2.2 任务查询响应字段（获取结果接口）

`GET /api/v4/extract/task/{task_id}` 返回字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `code` | int | 接口状态码，成功为 0 |
| `msg` | string | 接口处理信息，成功为 `ok` |
| `trace_id` | string | 请求 ID |
| `data.task_id` | string | 任务 ID |
| `data.data_id` | string | 解析对象数据 ID（若提交时传入了 `data_id`） |
| `data.state` | string | 任务状态：`pending`（排队中）、`running`（解析中）、`converting`（格式转换中）、`done`（完成）、`failed`（失败） |
| `data.full_zip_url` | string | 解析结果压缩包下载地址，`state=done` 时有效 |
| `data.err_msg` | string | 解析失败原因，`state=failed` 时有效 |
| `data.extract_progress.extracted_pages` | int | 已解析页数，`state=running` 时有效 |
| `data.extract_progress.total_pages` | int | 文档总页数，`state=running` 时有效 |
| `data.extract_progress.start_time` | string | 解析开始时间，`state=running` 时有效 |

批量查询接口 `GET /api/v4/extract-results/batch/{batch_id}` 在 `data.extract_result[]` 数组中返回每个文件的同类字段，并额外含 `file_name`，状态多一个 `waiting-file`（等待文件上传排队提交解析任务中）。

> 重要：自 2025-11-24 起，解析结果文件有效期为 30 天，过期后无法访问。MVP 与生产均应在任务完成后立即下载并落盘，不要长期依赖 `full_zip_url`。

### 2.3 Zip 包内文件清单（非 HTML 文件）

下载并解压 `full_zip_url` 后，根据后端（pipeline / vlm）与文档类型，主要包含以下文件（`{name}` 为原始文件名）：

| 文件 | 类别 | 用途 |
| --- | --- | --- |
| `full.md` | 内容主产物 | Markdown 解析结果，正文核心 |
| `{name}_content_list.json` | 结构化内容 | 按阅读顺序排列的扁平内容列表，最适合二次处理 |
| `{name}_content_list_v2.json` | 结构化内容 | 3.0 起新增，按页分组、统一 `type + content` 结构（开发版，结构可能变动） |
| `{name}_middle.json` | 结构化中间结果 | 保留完整版面层级（block/line/span + bbox），适合深度二次开发 |
| `{name}_model.json` | 模型原始输出 | 模型推理原始结果 |
| `{name}_layout.pdf` | 可视化调试 | 版面分析可视化，标注阅读顺序与块类型 |
| `{name}_span.pdf` | 可视化调试 | span 级标注，仅 pipeline 后端生成 |
| `images/` | 资源目录 | 图片、表格、公式截图等资源 |

官方文档将这些文件做了别名映射（在 API 文档中标注）：

- `layout.json` 对应中间处理结果（即 `middle.json`）
- `**_model.json` 对应模型推理结果（`model.json`）
- `**_content_list.json` 对应内容列表（`content_list.json`）
- `full.md` 为 Markdown 解析结果

### 2.4 HTML 文件输出差异

源文件为 HTML（`model_version="MinerU-HTML"`）时输出略有不同：

- `full.md`：Markdown 解析结果
- `main.html`：提取后的正文 HTML
- `extra_formats` 对 HTML 源文件无效

### 2.5 各文件字段详细说明

以下按"对接 LangExtract 的实用程度"由高到低说明。本项目建议以 `full.md`（喂给 LangExtract 的文本）+ `content_list.json`（提供阅读顺序与块级定位）为主，`middle.json` 作为需要精确坐标时的补充。

#### 2.5.1 `full.md`（Markdown 主产物）

- 多模态内容渲染规则：图片/图表块会先渲染截图；当存在可读内容时，会在图片后追加一个折叠的 HTML `<details>` 块，summary 标签优先使用块的 `sub_type`，否则回退到 image content / chart content。
- 表格在 Markdown 中以 HTML `<table>` 形式呈现。
- 行间公式以 LaTeX `$$...$$` 形式呈现。

#### 2.5.2 `content_list.json`（扁平内容列表，推荐对接 LangExtract）

这是 `middle.json` 的简化版，按阅读顺序将所有可读内容块以扁平结构存储，去除复杂版面信息，便于后续处理。

内容类型（`type` 字段取值）：

| type | 说明 |
| --- | --- |
| `image` | 图片 |
| `table` | 表格 |
| `chart` | 图表 |
| `text` | 文本 / 标题 |
| `equation` | 行间公式 |
| `code` | 代码块 / 算法块 |
| `list` | 列表 / 参考文献列表 |
| `header` / `footer` / `page_number` / `aside_text` / `page_footnote` | 页面辅助块 |

通用字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `type` | string | 内容类型 |
| `page_idx` | int | 所在页码，从 0 开始 |
| `bbox` | list[int] | 内容块边界框 `[x0, y0, x1, y1]`，归一化映射到 0–1000 区间 |
| `text` | string | 文本内容（`text` / `equation` 等类型） |
| `text_level` | int | 文本层级：无该字段或为 0 表示正文，1 表示一级标题，2 表示二级标题，依此类推 |

按类型扩展字段：

| 类型 | 扩展字段 | 说明 |
| --- | --- | --- |
| `equation` | `text`、`text_format`、`img_path` | `text` 为 LaTeX 文本，`text_format` 通常为 `latex`，`img_path` 为公式截图路径 |
| `image` | `img_path`、`image_caption`、`image_footnote`、可选 `sub_type` | caption/footnote 为字符串数组；`sub_type` 用于传递视觉子类型（如 `seal` 表示印章） |
| `chart` | `img_path`、`sub_type` | 视觉子类型传播 |
| `table` | `img_path`、`table_caption`、`table_footnote`、`table_body` | `table_body` 为 HTML 表格字符串 |
| `code` | `sub_type`（`code` / `algorithm`）、`code_body`、可选 `code_caption`、`code_footnote` | 区分普通代码与算法块 |
| `list` | 可选 `sub_type`、`list_items` | 区分普通列表与参考文献式列表 |

`content_list.json` 样例（节选，含坐标）：

```json
[
  {
    "type": "text",
    "text": "The response of flow duration curves to afforestation",
    "text_level": 1,
    "bbox": [62, 480, 946, 904],
    "page_idx": 0
  },
  {
    "type": "table",
    "img_path": "images/e3cb...d0.jpg",
    "table_caption": ["Table 2 Significance of the rainfall and time terms"],
    "table_footnote": ["..."],
    "table_body": "<html><body><table>...</table></body></html>",
    "bbox": [62, 480, 946, 904],
    "page_idx": 5
  },
  {
    "type": "equation",
    "img_path": "images/181e...e8.jpg",
    "text": "$$\nQ_{\\%} = f(P) + g(T)\n$$",
    "text_format": "latex",
    "bbox": [62, 480, 946, 904],
    "page_idx": 2
  }
]
```

#### 2.5.3 `content_list_v2.json`（3.0 新增，开发版）

按页分组的结构化输出，所有后端均额外输出，结构可能变动。

通用字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `type` | string | 内容类型 |
| `content` | dict | 该类型的结构化载荷 |
| `bbox` | list[int] | 可选边界框，映射到 0–1000 区间 |
| `anchor` | string | 可选锚点；部分 DOCX 标题或索引项含此字段 |

通用类型：

| type | 说明 |
| --- | --- |
| `title` | 标题块，含 `title_content` 与 `level` |
| `paragraph` | 段落块，含 `paragraph_content` |
| `equation_interline` | 行间公式，含 `math_content` 与 `math_type` |
| `image` / `table` / `chart` | 视觉块，含图片路径、caption 与相关结构化字段；印章为 `image` + `sub_type: "seal"` |
| `code` | 代码块，含 `code_content`、`code_caption`、`code_footnote`、`code_language` |
| `algorithm` | 算法块，含 `algorithm_content`、`algorithm_caption`、`algorithm_footnote` |
| `list` / `index` | 列表与索引块，含 `list_items` |
| `page_header` / `page_footer` / `page_number` / `page_aside_text` / `page_footnote` | 页面辅助块 |

说明：`title_content`、`paragraph_content`、caption 等内联字段通常是 span 列表；超链接 span 含 `content` 与 `url`，若一个链接内含不同样式的文本片段，还会含 `children`。

#### 2.5.4 `middle.json`（中间结构化结果，含完整版面层级）

顶层结构：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `pdf_info` | list[dict] | 每页解析结果数组 |
| `_backend` | string | 解析模式：`pipeline`、`vlm` 或 `office` |
| `_version_name` | string | MinerU 版本号 |

页信息结构（`pdf_info` 中每个元素）：

| 字段 | 说明 |
| --- | --- |
| `preproc_blocks` | PDF 预处理后未分段的中间结果 |
| `page_idx` | 页码，从 0 开始 |
| `page_size` | 页面宽高 `[width, height]` |
| `images` | 图片块信息列表 |
| `tables` | 表格块信息列表 |
| `interline_equations` | 行间公式块信息列表 |
| `discarded_blocks` | 待丢弃的块信息 |
| `para_blocks` | 分段后的内容块结果 |

块结构层级：

```
一级块 (table | image | chart)
└── 二级块
    └── lines
        └── spans
```

一级块字段：

| 字段 | 说明 |
| --- | --- |
| `type` | 块类型：`table`、`image` 或 `chart` |
| `bbox` | 块矩形框坐标 `[x0, y0, x1, y1]` |
| `blocks` | 包含的二级块列表 |

二级块字段：

| 字段 | 说明 |
| --- | --- |
| `type` | 块类型（见下表） |
| `bbox` | 块矩形框坐标 |
| `lines` | 包含的 line 信息列表 |

二级块类型：`image_body`、`image_caption`、`image_footnote`、`table_body`、`table_caption`、`table_footnote`、`chart_body`、`chart_caption`、`chart_footnote`、`text`、`title`、`index`、`list`、`interline_equation`。

line 与 span 结构：

- line 字段：`bbox`（line 矩形框坐标）、`spans`（包含的 span 列表）。
- span 字段：`bbox`（span 矩形框坐标）、`type`（`image` / `table` / `chart` / `text` / `inline_equation` / `interline_equation`）、`content` 或 `image_path`（文本内容或图片路径）。

VLM 后端的 `middle.json` 差异：

- `list` 成为二级块，新增 `sub_type` 区分列表类别（`text`：普通列表；`ref_text`：参考文献式列表）。
- 新增 `code` 块类型，含 `sub_type`（`code` / `algorithm`），至少含 `code_body`，可选 `code_caption`。
- `discarded_blocks` 可能含 `header`、`footer`、`page_number`、`aside_text`、`page_footnote` 等类型。
- 所有块含 `angle` 字段表示旋转角度（`0` / `90` / `180` / `270`）。

#### 2.5.5 `model.json`（模型推理原始结果）

pipeline 后端：二级嵌套结构外，单条记录字段为 `cls_id`、`label`、`score`、`bbox`、`index`。

VLM 后端：

- 两级嵌套列表：外层为页，内层为该页内容块。
- 每个块至少含 `type`、`bbox`、`angle`、`content`，部分类型增加 `score`、`block_tags`、`content_tags`、`format`。
- 坐标系：`bbox = [x0, y0, x1, y1]`（左上、右下），原点在页面左上角，**所有坐标为 [0,1] 区间的归一化百分比**（与 content_list 的 0–1000 映射不同，需注意区分）。
- 支持的 `type` 取值：`text`、`title`、`equation`、`image`、`image_caption`、`image_footnote`、`table`、`table_caption`、`table_footnote`、`phonetic`、`code`、`code_caption`、`ref_text`、`algorithm`、`list`、`header`、`footer`、`page_number`、`aside_text`、`page_footnote`。

#### 2.5.6 可视化文件

| 文件 | 用途 |
| --- | --- |
| `{name}_layout.pdf` | 每页版面分析可视化，右上角数字表示阅读顺序，不同背景色区分块类型；用于检查版面分析与阅读顺序是否正确 |
| `{name}_span.pdf` | 用不同颜色线框按 span 类型标注页面内容，用于排查文字丢失、行内公式识别、文本分割准确性；仅 pipeline 后端 |

## 3. 布局信息梳理与 LangExtract 对接

本节面向核心目标：**从 MinerU 输出中精准提取数值，并组织成 LangExtract 的纯文本 / `Document` 输入**。

### 3.1 坐标系统一（关键，避免数值错位）

MinerU 不同文件的 bbox 坐标系不一致，提取数值前必须先确认来源：

| 来源文件 | 坐标含义 | 取值范围 |
| --- | --- | --- |
| `content_list.json` / `content_list_v2.json` | 归一化映射 | 0–1000 整数 |
| `middle.json` | 原始页面坐标 | 像素 / pdf 单位，结合 `page_size` 使用 |
| `model.json`（VLM 后端） | 归一化百分比 | [0,1] 浮点 |

实务建议：

- 若只需"阅读顺序 + 块级定位"，用 `content_list.json`（0–1000）即可，无须换算。
- 若需"还原到具体像素/页面位置"（如裁剪原图、与原 PDF 对位），用 `middle.json` 的 `bbox` 配合该页 `page_size`。
- 不要混用两套坐标系做同一计算。

### 3.2 阅读顺序与页面定位

- `content_list.json` 已按阅读顺序排列，可直接顺序遍历重建文档逻辑流。
- 每个块的 `page_idx`（从 0 开始）提供页级定位。
- `middle.json` / `model.json` 中可结合 `index`（阅读顺序索引）做更细的排序还原。
- `layout.pdf` 右上角数字是阅读顺序的可视化，调试时用于核对自动排序是否合理。

### 3.3 面向数值提取的块类型处理策略

针对"精准提取数值"的目标，按块类型采取不同策略：

| 块类型 | 数值所在字段 | 提取策略 |
| --- | --- | --- |
| `text` | `text` | 直接取文本，正文数值通过 LangExtract 抽取 |
| `table` | `table_body`（HTML） | 解析 HTML 表格还原行列结构，单元格数值可精确定位到行列 |
| `equation` | `text`（LaTeX） | 保留 LaTeX 原文，按需解析公式中的数值/变量 |
| `image` / `chart` | `img_path` + caption | 数值若在图内，需对 `images/` 中截图做二次 OCR/识别；caption/footnote 文本直接可用 |
| `list` | `list_items` / `text` | 列表项中的数值按条目提取 |

要点：

- 表格是数值密度最高的块。`table_body` 是 HTML 字符串，建议用 HTML 解析器还原为二维结构后再定位单元格，避免直接正则误匹配。
- 图表（chart）中的数值通常不在文本里，`content_list` 仅给 `img_path` 与 caption；若数值在图内，需对截图二次识别，这部分不在 MinerU 文本输出覆盖范围内。
- 公式数值以 LaTeX 表达，提取时注意上下标与转义。

### 3.4 推荐的 LangExtract 对接链路

LangExtract 核心 pipeline 只接受纯文本或文本型 `Document`（参见 `langextract_pipeline_spec.md` 第 1 节），不解析 PDF/图片等原始文件。因此 MinerU 正是 LangExtract 前置的"文档解析层"。推荐链路：

```text
原始文档 (PDF/Word/PPT/Excel/图片/HTML)
  -> MinerU 精准解析 API (路径 B)
  -> 下载并解压 full_zip_url
  -> 读取 content_list.json (阅读顺序 + 块级定位 + 0-1000 bbox)
  -> 按块类型构造文本:
       text/list      -> 直接拼接为正文文本
       table          -> table_body(HTML) 转为可读文本/Markdown 表格
       equation       -> 保留 LaTeX
       image/chart     -> 保留 caption, 必要时二次识别截图
  -> 组装为 langextract Document.text (并保留 page_idx/bbox 作为下游溯源元数据)
  -> langextract.extract() 进行结构化数值抽取
  -> AnnotatedDocument / JSONL 输出
```

下游溯源建议：将 MinerU 的 `page_idx`、`bbox`、块 `type` 作为自定义元数据随文本块一起保留（LangExtract 的 `Document.additional_context` 或外部映射表），以便抽取结果回溯到原文档的页与位置。

### 3.5 块到 LangExtract 输入的字段映射建议

| MinerU 字段 | LangExtract 用途 | 说明 |
| --- | --- | --- |
| `text` / `table_body` / `list_items` | `Document.text` 来源 | 拼接为待抽取正文 |
| `page_idx` | 下游溯源元数据 | 定位原文档页码 |
| `bbox` | 下游溯源元数据 | 块在页面中的位置（注意 0–1000 坐标系） |
| `type` | 分块/分流依据 | 决定该块是否进入正文、是否需二次识别 |
| `text_level` | 文档结构线索 | 标题层级，可用于分段或 chunk 边界 |

## 4. 执行 MVP 的必要与必须字段

本项目 MVP 采用路径 B（精准解析 API），必须申请 Token。以下区分"必须配置项"与"接口必填字段"。

### 4.1 必须的外部配置（运行前提）

| 配置项 | 是否必须 | 说明 |
| --- | --- | --- |
| MinerU API Token | 必须 | 在 mineru.net API 管理页申请；v2/v3 已于 2025-01-17 停服，必须使用 v4 新域名并重新创建 Token |
| 出站网络 | 必须 | 需可访问 `mineru.net` 及结果域名 `cdn-mineru.openxlab.org.cn` / OSS 域名 |
| 测试文件 | 必须 | 本地文件或公网 URL（≤200MB、≤200 页；海外 URL 易超时） |

推荐用环境变量 + `.env` 管理 Token（不要硬编码、不要提交到 git）：

```bash
# .env （加入 .gitignore）
MINERU_API_TOKEN=你申请到的token
MINERU_API_BASE=https://mineru.net/api/v4
```

请求头格式（必须）：

```python
header = {
    "Content-Type": "application/json",
    "Authorization": f"Bearer {token}",  # Bearer 后必须有空格，漏写返回 A0202
}
```

### 4.2 创建解析任务的必填字段

#### 单文件 URL 解析（`POST /api/v4/extract/task`）

| 字段 | 类型 | 是否必填 | 说明 |
| --- | --- | --- | --- |
| `url` | string | 必填 | 文件 URL，支持各类文档与图片格式 |
| `model_version` | string | 条件必填 | 解析 HTML 文件时必须为 `MinerU-HTML`；非 HTML 可选 `pipeline`（默认）/ `vlm`（推荐）。MVP 建议显式指定 |

最小可用请求体（非 HTML）：

```json
{
  "url": "https://cdn-mineru.openxlab.org.cn/demo/example.pdf",
  "model_version": "vlm"
}
```

#### 本地文件批量上传（`POST /api/v4/file-urls/batch`）

| 字段 | 类型 | 是否必填 | 说明 |
| --- | --- | --- | --- |
| `files[].name` | string | 必填 | 文件名，强烈建议带正确后缀 |
| `model_version` | string | 条件必填 | 同上规则 |

流程：申请上传链接 -> 对返回的 `file_urls[i]` 用 PUT 上传文件 -> 系统自动提交解析 -> 轮询 `batch_id` 结果。

### 4.3 MVP 常用可选字段（按需开启）

| 字段 | 默认 | 适用模型 | 说明 |
| --- | --- | --- | --- |
| `is_ocr` | false | pipeline / vlm | 扫描件/图片需开启 |
| `enable_formula` | true | pipeline / vlm | 公式识别（vlm 下仅影响行内公式） |
| `enable_table` | true | pipeline / vlm | 表格识别（数值密集文档建议保持开启） |
| `language` | ch | pipeline / vlm | 文档语言，影响 OCR 效果 |
| `extra_formats` | 无 | 全部 | 额外导出 `docx`/`html`/`latex`，对 HTML 源文件无效 |
| `page_ranges` | 全部 | 全部 | 指定页码范围，如 `"2,4-6"` |
| `data_id` | 无 | 全部 | 业务数据唯一标识，便于回查 |
| `callback` + `seed` | 无 | 全部 | 回调通知；用 callback 时 `seed` 必填 |

### 4.4 MVP 执行最小闭环

```text
1. 配置 MINERU_API_TOKEN（环境变量/.env）
2. POST /api/v4/extract/task  提交 url + model_version  -> 拿 task_id
3. 轮询 GET /api/v4/extract/task/{task_id}  直到 state=done
4. 下载 full_zip_url 并解压（30 天内有效，立即落盘）
5. 读取 full.md 与 content_list.json
6. 按第 3 节策略组装文本 -> 对接 langextract.extract()
```

### 4.5 常见错误码（MVP 排错）

| 错误码 | 说明 | 解决建议 |
| --- | --- | --- |
| `A0202` | Token 错误 | 检查 Token 与 `Bearer ` 前缀 |
| `A0211` | Token 过期 | 更换新 Token |
| `-500` | 传参错误 | 检查参数类型与 Content-Type |
| `-10002` | 请求参数错误 | 检查请求参数格式 |
| `-60002` | 获取匹配文件格式失败 | 文件名/链接带正确后缀，且为支持的格式 |
| `-60005` | 文件大小超出限制 | ≤ 200MB |
| `-60006` | 文件页数超过限制 | 拆分文件后重试 |
| `-60008` | 文件读取超时 | 检查 URL 可访问（避免海外 URL） |
| `-60012` | 找不到任务 | 确认 `task_id` 有效且未删除 |
| `-60015` / `-60016` | 文件/格式转换失败 | 手动转 PDF 或换导出格式重试 |
| `-60018` | 每日解析任务数量达上限 | 次日再试 |

## 5. 附：两套 API 对比（选型参考）

| 维度 | 🎯 精准解析 API（本项目路径 B） | ⚡ Agent 轻量解析 API |
| --- | --- | --- |
| 是否需要 Token | 需要 | 不需要（IP 限频） |
| 接口地址 | `/api/v4/extract/task`、`/api/v4/file-urls/batch` | `/api/v1/agent/parse/url`、`/api/v1/agent/parse/file` |
| 模型版本 | pipeline（默认）/ vlm（推荐）/ MinerU-HTML | 固定 pipeline 轻量模型 |
| 文件大小上限 | 200 MB | 10 MB |
| 页数上限 | 200 页 | 20 页 |
| 批量支持 | 支持（≤ 200 个） | 不支持，单文件 |
| 输出格式 | Zip 包（Markdown + JSON，可导出 docx/html/latex） | 仅 Markdown（CDN 链接） |
| 输入格式 | PDF/图片/Doc(x)/Ppt(x)/Xls(x)/HTML | PDF/图片/Docx/PPTx/Xlsx（不支持 HTML） |
| 调用方式 | 异步（提交 → 轮询） | 异步（提交 → 轮询） |

> 选型结论：本项目需要 vlm 模型、表格/公式精度、JSON 结构化输出与布局信息，必须采用路径 B。轻量 API 仅适合零配置快速验证链路，不满足数值精准提取与 LangExtract 结构化对接需求。

## 6. 信息来源

- MinerU API 官方文档：https://mineru.net/apiManage/docs
- MinerU 输出文件格式参考：https://opendatalab.github.io/MinerU/reference/output_files/

内容已按本项目需求重新组织与转述。

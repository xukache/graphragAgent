# MinerU 文档解析规范 v1.0（实测校准版）

本规范以 **本项目实际跑通的 MinerU 精准解析 API（路径 B）pipeline 输出为准**，并对照官方文档（https://mineru.net/apiManage/docs 与 https://opendatalab.github.io/MinerU/reference/output_files/）逐项校准。

> 校准原则：**凡本地实际输出与官方文档冲突，一律以本地实际输出为准**，并在文中以「⚠️ 实测校准」标注差异，保留官方说法作为对照。

实测环境信息（来自本次运行的真实结果）：

| 项 | 实测值 | 来源 |
| --- | --- | --- |
| 后端 `_backend` | `hybrid` | `layout.json` 顶层字段 |
| 版本 `_version_name` | `3.1.8` | `layout.json` 顶层字段 |
| 请求 `model_version` | `vlm` | pipeline 配置（实际后端落为 hybrid） |
| 测试文件 | `sample.pdf`（1 页，含标题/正文/数值表格/公式行） | 本地生成 |
| 任务状态流转 | `waiting-file → pending → running → done` | 轮询日志 |

本文档结构：

1. 完整 pipeline 执行思路 + 实测脚本存放位置
2. 实际输出文件清单（实测 vs 官方对比，以实测为准）
3. 各文件实际字段规范（实测 vs 官方对比，以实测为准）
4. pipeline 关键参数规范（便于灵活调整）
5. 布局信息与 LangExtract 对接
6. 信息来源

---

## 1. 完整 Pipeline 执行思路与脚本位置

### 1.1 脚本存放位置

所有 MVP 测试代码位于项目根目录下的独立文件夹 **`mineru_mvp/`**：

| 文件 | 作用 |
| --- | --- |
| `mineru_mvp/.env` | 配置与 Token（已 `.gitignore`，禁止提交） |
| `mineru_mvp/.gitignore` | 忽略 `.env`、`output/`、`.venv/` |
| `mineru_mvp/pyproject.toml` | 依赖声明（uv 项目统一用 pyproject.toml，不用 requirements.txt） |
| `mineru_mvp/make_sample_pdf.py` | 生成测试用 PDF（含中文标题、正文、数值表格、公式行） |
| `mineru_mvp/mineru_pipeline.py` | **主 pipeline**：上传 → 轮询 → 下载 → 解压 → 落盘 → 概览 |
| `mineru_mvp/README.md` | 使用说明 |
| `mineru_mvp/sample.pdf` | 生成的测试 PDF |
| `mineru_mvp/output/` | 解析结果落盘目录（运行后生成） |

运行方式：

```bash
cd mineru_mvp

# ⚠️ 必须先进入子虚拟环境（环境隔离要求，详见 AGENTS.md）
# 方式一：使用 uv run（推荐，自动使用 .venv 解释器，无须 activate）
uv run python make_sample_pdf.py          # 1) 生成本地测试 PDF
uv run python mineru_pipeline.py          # 2) 解析 sample.pdf（或传入自定义路径）
uv run python mineru_pipeline.py /path/to/your.pdf

# 方式二：先 activate 再运行
source .venv/bin/activate.fish   # fish shell
# source .venv/bin/activate      # bash/zsh
python make_sample_pdf.py
python mineru_pipeline.py
```

> **环境隔离说明**：`mineru_mvp/.venv` 由 `uv` 创建（Python 3.11），与项目其他组件（langextract、graphrag 等）完全隔离。禁止在项目根环境或系统环境中直接运行 mineru 脚本或安装其依赖。详见项目根目录 `AGENTS.md`。

依赖管理：

```bash
cd mineru_mvp
uv sync                    # 从 pyproject.toml 同步安装所有依赖到 .venv
# 添加新依赖：uv add <package>
# 移除依赖：uv remove <package>
```

### 1.2 执行思路（本地文件 → 云端解析 → 本地存储）

本项目 MVP 解析的是 **本地 PDF 文件**，因此必须走「批量上传接口」链路（单文件 `POST /api/v4/extract/task` 仅接受文件 URL，不支持本地文件直传）。

#### 虚拟环境前置要求

mineru_mvp 组件使用独立的 `uv` 虚拟环境，**任何操作前必须确认使用的是 `.venv` 内的 Python**：

```bash
# 确认解释器路径
mineru_mvp/.venv/bin/python --version
# 应输出 Python 3.11.x

# 若需安装/更新依赖
cd mineru_mvp && uv sync
```

禁止在项目根环境或系统 Python 中运行 mineru 脚本。这是为了避免与后续 langextract、graphrag 等组件的依赖版本冲突。

#### 完整链路

```text
[本地 PDF 加载]
   make_sample_pdf.py 生成 sample.pdf（或用户提供本地 PDF）
        │
        ▼
[1] 申请上传链接  POST /api/v4/file-urls/batch
        │  请求体携带 files[].name + model_version + 解析开关
        │  返回 batch_id + file_urls[0]（OSS 签名 PUT 链接）
        ▼
[2] 上传文件      PUT <file_urls[0]>  （二进制 body）
        │  ⚠️ 不带 Authorization / Content-Type，否则 OSS 签名校验失败
        │  上传完成后系统自动提交解析任务，无须再调用提交接口
        ▼
[3] 轮询结果      GET /api/v4/extract-results/batch/{batch_id}
        │  state: waiting-file → pending → running → done
        │  done 时返回 full_zip_url
        ▼
[4] 下载并解压    GET <full_zip_url>
        │  ⚠️ 结果 CDN 为国内域名，若本机走代理可能 SSL EOF
        │     pipeline 已实现：失败后自动「绕过代理直连」重试
        │  解压到 output/，并保留 result.zip 原始包
        ▼
[5] 本地存储与概览
        保存 task_meta.json（batch_id / file_name / data_id / full_zip_url / state）
        统计 content_list.json 块类型，预览 full.md
```

### 1.3 实测踩坑与对策（已固化进脚本）

| 现象 | 根因 | 对策（已在脚本中实现） |
| --- | --- | --- |
| `401 A0202 user authenticate failed` | Token 末尾被误粘多余字符（HS512 签名应为 86 个 base64url 字符） | 校验 Token 完整性；`.env` 存放干净 Token |
| 下载结果 `SSL: UNEXPECTED_EOF_WHILE_READING` | 本机全局代理（如 `127.0.0.1:7897`）转发国内 CDN 域名时 TLS 中断 | `_download_zip()` 第 1 次按系统代理，失败后自动 `proxies={"http":None,"https":None}` 绕过代理直连重试 |
| 中文渲染成 ■ | 源 PDF 字体无 CJK 字形（非 MinerU 问题） | `make_sample_pdf.py` 注册内置 CID 字体 `STSong-Light` |
| PUT 上传 OSS 失败 | 误带了 `Authorization`/`Content-Type` 头 | 上传请求只发二进制 body，不带任何鉴权头 |

### 1.4 实测运行结果（成功）

```text
[1/5] 申请上传链接 -> batch_id=4b3c0c19-...
[2/5] 上传文件 sample.pdf -> OSS  上传成功
[3/5] 轮询解析结果  state=waiting-file → pending → running → 解析完成
[4/5] 下载并解压结果  （第 1 次系统代理失败 → 第 2 次绕过代理直连成功）  共 7 个条目
[5/5] content_list.json 块类型统计: table:1  text:9
Pipeline 执行完成 ✅
```

表格数值精确还原（`1280.50 / 210.30 / 42.1 ... 全年 5867.35 / 1035.45 / 43.9`），中文正文完整。

---

## 2. 实际输出文件清单（实测为准）

### 2.1 实测 ZIP 实际包含的文件（7 个条目）

下载 `full_zip_url` 解压后，**实际产物如下**（`{uuid}` 为 MinerU 分配的任务 UUID，本次为 `3162dec8-e86e-4170-b36c-13ff86d2c56b`）：

| 实际文件名 | 大小(B) | 类别 | 说明 |
| --- | --- | --- | --- |
| `full.md` | 1225 | 内容主产物 | Markdown 解析结果 |
| `{uuid}_content_list.json` | 3232 | 结构化内容 | 扁平内容列表（阅读顺序 + 0–1000 bbox） |
| `{uuid}_content_list_v2.json` | 5387 | 结构化内容 | 按页分组、统一 `type + content` 结构 |
| `{uuid}_model.json` | 5840 | 模型原始输出 | 模型推理结果，bbox 为 [0,1] 归一化 |
| `layout.json` | 34547 | 结构化中间结果 | **即官方所称 `middle.json`**，含完整版面层级 |
| `{uuid}_origin.pdf` | 3538 | 原始文件副本 | 原始 PDF 回传副本 |
| `images/{sha256}.jpg` | 45347 | 资源 | 表格/图片/公式截图 |

### 2.2 ⚠️ 实测校准：与官方文档的冲突点（以实测为准）

| 项 | 官方文档说法 | 实测实际输出 | 处理 |
| --- | --- | --- | --- |
| 文件命名前缀 | `{original_filename}_xxx.json`（用原文件名） | **`{uuid}_xxx.json`**（用任务 UUID，原文件名不参与命名） | 以实测为准：按 UUID 前缀匹配 |
| 中间结果文件名 | `{name}_middle.json` | **`layout.json`**（固定名，无 uuid 前缀、无 `_middle` 后缀） | 以实测为准；官方 API 页也注明「`layout.json` 对应 middle.json」 |
| 可视化文件 | 生成 `{name}_layout.pdf` 与 `{name}_span.pdf` | **均未生成** | 以实测为准：vlm/hybrid 后端本次未输出可视化 PDF |
| 原始 PDF 副本 | 文件清单未提及 | **额外生成 `{uuid}_origin.pdf`** | 以实测为准：补充进清单 |
| `_backend` 取值 | `pipeline` / `vlm` / `office` | **`hybrid`** | 以实测为准：新增 `hybrid` 取值 |
| 文件总数 | 文档罗列约 8 类（含两份 PDF 可视化、middle.json 等） | **实际 7 个条目**（如上表） | 以实测为准 |

> 结论：**对接代码不要假设文件名带原始文件名**。应按以下稳健规则定位：
> - Markdown：固定 `full.md`
> - 内容列表：`*content_list.json`（glob 匹配）
> - V2 内容列表：`*content_list_v2.json`
> - 模型输出：`*model.json`
> - 中间版面结果：固定 `layout.json`
> - 原始 PDF：`*origin.pdf`
> - 资源：`images/` 目录

### 2.3 HTML 源文件输出差异（官方说明，未实测）

源文件为 HTML（`model_version="MinerU-HTML"`）时官方称输出 `full.md` + `main.html`，且 `extra_formats` 无效。本项目未对 HTML 实测，沿用官方说明，待实测后再校准。

---

## 3. 各文件实际字段规范（实测为准）

### 3.1 `full.md`（Markdown 主产物）

实测特征：

- 标题以 `#` 表示（实测一级标题均渲染为 `# `）。
- 表格以 HTML `<table>...</table>` 内联呈现（非 Markdown 管道表格）。
- 实测样例中公式以普通文本行出现（源 PDF 中公式为普通文字 `毛利率 = (营业收入 - 营业成本) / 营业收入 x 100%`，未触发 LaTeX 块）。
- 官方称图片/图表块会先渲染截图，再追加折叠 `<details>` 块；本次样例无图片，未触发，沿用官方说明。

### 3.2 `{uuid}_content_list.json`（扁平内容列表，**推荐对接 LangExtract**）

实测结构：顶层为数组，每个元素是一个内容块，按阅读顺序排列。

实测出现的字段：

| 字段 | 类型 | 实测说明 |
| --- | --- | --- |
| `type` | string | 实测出现 `text`、`table` |
| `text` | string | `text` 块的文本内容 |
| `text_level` | int | 实测：标题为 `1`；正文段落**无此字段**（即正文不带 text_level） |
| `bbox` | list[int] | `[x0,y0,x1,y1]`，实测为 **0–1000 归一化整数**（实测最大值 878，符合 0–1000 区间） |
| `page_idx` | int | 页码，从 0 开始 |

`table` 类型实测扩展字段：

| 字段 | 类型 | 实测值 |
| --- | --- | --- |
| `img_path` | string | `images/{sha256}.jpg`（表格截图） |
| `table_caption` | list | 实测为空数组 `[]` |
| `table_footnote` | list | 实测为空数组 `[]` |
| `table_body` | string | 完整 HTML 表格字符串，单元格数值精确 |

实测真实片段：

```json
[
  { "type": "text", "text": "MinerU MVP 测试样例文档 ", "text_level": 1,
    "bbox": [317, 74, 678, 99], "page_idx": 0 },
  { "type": "text", "text": "本文档用于验证 MinerU 精准解析 API（路径 B）...",
    "bbox": [97, 165, 873, 221], "page_idx": 0 },
  { "type": "table",
    "img_path": "images/2675...773c.jpg",
    "table_caption": [], "table_footnote": [],
    "table_body": "<table><tr><td>季度</td><td>营业收入</td>...<td>43.9</td></tr></table>",
    "bbox": [161, 306, 835, 439], "page_idx": 0 }
]
```

⚠️ 实测校准：

- **标题在实测中 `type` 为 `text` + `text_level:1`，而非独立的 `title` 类型**。这与官方"text 类型用 text_level 区分标题"一致，对接时不要期望 content_list.json 里出现 `title` 这个 type 值。
- 官方列出的 `equation`/`code`/`list`/`chart`/`image`/`header` 等类型本次样例未触发，沿用官方定义，待相应文档实测后校准。

### 3.3 `{uuid}_content_list_v2.json`（按页分组，统一 type+content）

实测结构：顶层为 **二维数组**（外层按页分组，内层为该页块列表）。

实测通用字段：

| 字段 | 类型 | 实测说明 |
| --- | --- | --- |
| `type` | string | 实测出现 `title`、`paragraph`、`table` |
| `content` | dict | 该类型的结构化载荷 |
| `bbox` | list[int] | 0–1000 归一化（实测无 `anchor` 字段） |

实测各类型 `content` 结构：

`title`：
```json
{ "type": "title",
  "content": { "title_content": [ {"type":"text","content":"1. 文档目的"} ], "level": 1 },
  "bbox": [100,137,221,158] }
```

`paragraph`：
```json
{ "type": "paragraph",
  "content": { "paragraph_content": [ {"type":"text","content":"本文档用于验证..."} ] },
  "bbox": [97,165,873,221] }
```

`table`（⚠️ 实测字段名与官方/与 v1 不同）：
```json
{ "type": "table",
  "content": {
    "image_source": { "path": "images/2675...773c.jpg" },
    "table_caption": [],
    "table_footnote": [],
    "html": "<table>...</table>",
    "table_type": "simple_table",
    "table_nest_level": 1
  },
  "bbox": [161,306,835,439] }
```

⚠️ 实测校准（content_list_v2 表格）：

- 截图路径在 **`content.image_source.path`**，不是 `img_path`。
- 表格 HTML 在 **`content.html`**，不是 `table_body`。
- 实测额外字段：**`table_type`（如 `simple_table`）、`table_nest_level`（如 `1`）**，官方文档未列出。
- v2 中标题/段落是独立的 `title` / `paragraph` 类型（与 content_list.json 的 `text+text_level` 表达方式不同，二者需分别处理）。

### 3.4 `layout.json`（= 官方 middle.json，中间版面层级）

实测顶层字段：

| 字段 | 类型 | 实测值 |
| --- | --- | --- |
| `pdf_info` | list[dict] | 每页解析结果数组（实测 1 页） |
| `_backend` | string | **`hybrid`**（官方文档称 pipeline/vlm/office，实测为 hybrid） |
| `_ocr_enable` | bool | ⚠️ 官方未列出，实测存在 |
| `_vlm_ocr_enable` | bool | ⚠️ 官方未列出，实测存在 |
| `_version_name` | string | `3.1.8` |

实测 `pdf_info[i]` 页字段：

| 字段 | 实测说明 |
| --- | --- |
| `preproc_blocks` | 预处理后块（含 `bbox`/`type`/`angle`/`index`/`lines`） |
| `discarded_blocks` | 实测为空数组 |
| `page_size` | **`[595, 841]`**（A4 像素，原始页面坐标，非归一化） |
| `page_idx` | 页码，从 0 |
| `para_blocks` | 分段后块（实测 10 个） |

实测 block / line / span 结构：

```json
{
  "bbox": [189, 63, 404, 84],
  "type": "title",
  "angle": 0,
  "index": 0,
  "lines": [
    { "bbox": [189,63,405,85],
      "spans": [ {"bbox":[189,63,405,85],"type":"text","content":"MinerU MVP 测试样例文档","score":1.0} ] }
  ]
}
```

实测要点：

- **`bbox` 为原始页面像素坐标**（与 `page_size` [595,841] 同一坐标系），与 content_list 的 0–1000 不同。
- 每块带 `index`（阅读顺序索引）与 `angle`（旋转角度，实测 0）。
- span 带 `score`（实测均为 1.0）。

### 3.5 `{uuid}_model.json`（模型推理原始结果）

实测结构：**二维数组**（外层页，内层块）。

实测块字段：

| 字段 | 类型 | 实测说明 |
| --- | --- | --- |
| `type` | string | 实测出现 `title`、`text`、`table`、**`ocr_text`** |
| `bbox` | list[float] | **`[0,1]` 区间归一化浮点**（如 `[0.319,0.075,0.68,0.1]`） |
| `angle` | int | 旋转角度，实测 0 |
| `content` | string/null | 实测：`table` 块为 HTML 字符串；`title`/`text` 块为 **`null`**（正文文本不在 model.json，而在 layout.json / content_list.json） |
| `merge_prev` | bool | 仅 `text` 块出现，标识是否与前块合并 |
| `score` | float | 仅 `ocr_text` 块出现，实测 1.0 |
| `text` | string | 仅 `ocr_text` 块出现，实测多为空串 |

实测块类型统计：`title:5, text:4, table:1, ocr_text:13`。

⚠️ 实测校准（model.json）：

- 实测出现 **`ocr_text`** 类型，官方 VLM 后端 `type` 列表中未列出。
- 实测字段为 `type/bbox/angle/content/merge_prev/score/text`；官方称"可能含 `block_tags`/`content_tags`/`format`"，本次**未出现**这些字段。
- 普通 `title`/`text` 的 `content` 为 `null`（文本需到 `layout.json` 或 `content_list.json` 取）。
- 坐标系为 **[0,1] 归一化**，与 content_list（0–1000）、layout.json（像素）三者均不同。

### 3.6 三套坐标系实测对照（关键，避免数值错位）

同一"标题块"在三个文件中的坐标表达（实测）：

| 文件 | bbox 示例 | 坐标系 |
| --- | --- | --- |
| `{uuid}_model.json` | `[0.319, 0.075, 0.68, 0.1]` | **[0,1] 归一化浮点** |
| `{uuid}_content_list.json` | `[317, 74, 678, 99]` | **0–1000 归一化整数** |
| `layout.json` | `[189, 63, 404, 84]`（配合 page_size `[595,841]`） | **原始页面像素** |

换算关系（实测验证）：`content_list ≈ model × 1000`；`layout = 原始像素`。**三者不可混用**。

### 3.7 `images/` 与 `{uuid}_origin.pdf`

- `images/{sha256}.jpg`：表格/图片/公式的截图，文件名为内容哈希。`content_list.json` 的 `img_path`、`content_list_v2.json` 的 `content.image_source.path` 均指向此目录。
- `{uuid}_origin.pdf`：原始 PDF 的回传副本（⚠️ 官方文件清单未提及，实测存在）。

---

## 4. Pipeline 关键参数规范（便于灵活调整）

所有参数集中在 `mineru_mvp/.env`，由 `MineruConfig.from_env()` 读取。分三类。

### 4.1 鉴权与连接参数（必须）

| 参数（.env 键） | 默认/实测值 | 说明 | 调整建议 |
| --- | --- | --- | --- |
| `MINERU_API_TOKEN` | （必填） | Bearer Token；HS512 签名应为 86 个 base64url 字符 | 过期换新（错误码 A0211）；勿粘入多余字符（A0202） |
| `MINERU_API_BASE` | `https://mineru.net/api/v4` | API 基址，固定 v4 | v2/v3 已停服，勿改回旧版 |

请求头（脚本固定，必须）：`Content-Type: application/json` + `Authorization: Bearer <token>`（Bearer 后必须有空格）。

### 4.2 解析行为参数（可灵活调整）

| 参数（.env 键） | 默认 | 实测值 | API 字段 | 作用与调整建议 |
| --- | --- | --- | --- | --- |
| `MINERU_MODEL_VERSION` | `vlm` | `vlm`（实际后端落为 `hybrid`） | `model_version` | `pipeline`/`vlm`/`MinerU-HTML`。HTML 文件必须 `MinerU-HTML`；非 HTML 推荐 `vlm` |
| `MINERU_LANGUAGE` | `ch` | `ch` | `language` | 影响 OCR；仅 pipeline/vlm 有效 |
| `MINERU_ENABLE_TABLE` | `true` | `true` | `enable_table` | 数值密集文档务必保持 `true`（实测表格精确还原） |
| `MINERU_ENABLE_FORMULA` | `true` | `true` | `enable_formula` | 公式识别；vlm 下仅影响行内公式 |
| `MINERU_IS_OCR` | `false` | `false` | `file.is_ocr` | 扫描件/图片需置 `true` |

⚠️ 实测说明：请求 `model_version=vlm`，但结果 `_backend` 实测为 `hybrid`（3.1.8 版本服务端可能将 vlm 路由到 hybrid 混合后端）。对接时应**以输出文件实际结构为准**，不要假设后端等于请求值。

未在 .env 暴露、但接口支持的可选参数（按需在代码中加入 `file_entry` / payload）：

| API 字段 | 说明 |
| --- | --- |
| `data_id` | 业务数据唯一标识（脚本已用 `mineru_mvp_001` 演示） |
| `page_ranges` | 页码范围，如 `"2,4-6"`（批量接口为 `file.page_ranges`） |
| `extra_formats` | 额外导出 `docx`/`html`/`latex`，对 HTML 源无效 |
| `callback` + `seed` | 回调通知；用 callback 时 seed 必填 |
| `no_cache` / `cache_tolerance` | 缓存控制（URL 解析接口） |

### 4.3 轮询与下载参数（工程鲁棒性）

| 参数（.env 键） | 默认 | 说明 | 调整建议 |
| --- | --- | --- | --- |
| `MINERU_POLL_INTERVAL` | `5`（秒） | 轮询间隔 | 大文档可增大以降低请求数 |
| `MINERU_POLL_TIMEOUT` | `600`（秒） | 轮询总超时 | 200 页大文档应上调 |

下载鲁棒性（脚本内 `_download_zip`，无 .env 开关）：

- 重试 `max_retries=4`，递增退避 `2*attempt` 秒。
- 第 1 次按系统代理；**第 2 次起自动绕过代理直连**（解决国内 CDN 经代理 SSL EOF）。

### 4.4 参数与文件类型适配速查

| 文件类型 | model_version | is_ocr | 备注 |
| --- | --- | --- | --- |
| 普通 PDF（电子版） | `vlm` | `false` | 默认配置即可 |
| 扫描件 PDF / 图片 | `vlm` 或 `pipeline` | `true` | 必须开 OCR |
| HTML | `MinerU-HTML` | — | extra_formats 无效 |
| Word/PPT/Excel | `vlm` 或 `pipeline` | `false` | 后端转换后解析 |

---

## 5. 布局信息与 LangExtract 对接

### 5.1 推荐对接文件

对接 LangExtract（仅接受纯文本 / 文本型 `Document`，参见 `langextract_pipeline_spec.md`）时，**以 `content_list.json` 为主**：它已按阅读顺序排列、带 `page_idx` 与 0–1000 `bbox`，便于构造正文并保留溯源元数据。

### 5.2 按块类型构造文本（基于实测块类型）

| content_list 块 | 数值/文本来源 | 处理 |
| --- | --- | --- |
| `text`（含 `text_level`） | `text` | 直接拼接；`text_level` 用于分段/chunk 边界 |
| `table` | `table_body`（HTML） | 用 HTML 解析器还原行列，再定位单元格数值（实测数值精确，勿用裸正则） |
| `equation`（本次未触发） | `text`（LaTeX） | 保留 LaTeX 原文 |
| `image`/`chart`（本次未触发） | `img_path` + caption | caption 直接用；图内数值需对 `images/` 截图二次识别 |

### 5.3 对接链路

```text
本地 PDF
  -> mineru_pipeline.py（路径 B：上传→轮询→下载→解压→落盘）
  -> 读取 output/{uuid}_content_list.json
  -> 按块类型构造文本（text 拼接 / table HTML 转可读 / equation 保留 LaTeX）
  -> 组装 langextract Document.text，page_idx+bbox+type 作为溯源元数据
  -> langextract.extract()
  -> AnnotatedDocument / JSONL
```

### 5.4 字段映射建议

| MinerU 字段（content_list.json） | LangExtract 用途 |
| --- | --- |
| `text` / `table_body` | `Document.text` 来源 |
| `page_idx` | 下游溯源（页码） |
| `bbox`（0–1000） | 下游溯源（位置） |
| `type` / `text_level` | 分块、分流、chunk 边界 |

---

## 6. 信息来源

- MinerU API 官方文档：https://mineru.net/apiManage/docs
- MinerU 输出文件格式参考：https://opendatalab.github.io/MinerU/reference/output_files/
- 本地实测：`mineru_mvp/` pipeline 实际运行结果（`_backend=hybrid`，`_version_name=3.1.8`，2026-05-30）

> 凡本规范「⚠️ 实测校准」标注处，均以本地实际输出为准，官方文档说法仅作对照。后续若解析其他文档类型（含图片/公式/列表/HTML），应补充实测并继续校准本规范。

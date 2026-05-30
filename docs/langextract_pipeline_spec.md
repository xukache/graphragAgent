# LangExtract Pipeline 规范文档

本文档基于当前本地源码 `langextract_src/` 分析，说明 LangExtract 核心 pipeline 的输入规范、文本模型接入规范，以及 pipeline 输出数据格式规范。

## 1. Pipeline 输入规范

LangExtract 的核心入口是 `langextract.extract()`，源码位于：

- `langextract_src/langextract/extraction.py`
- `langextract_src/langextract/core/data.py`
- `langextract_src/langextract/io.py`

核心函数签名中的输入参数为：

```python
def extract(
    text_or_documents: str | Iterable[data.Document],
    prompt_description: str | None = None,
    examples: Sequence[Any] | None = None,
    ...
) -> list[data.AnnotatedDocument] | data.AnnotatedDocument
```

### 1.1 支持的输入类型

LangExtract 原生支持以下输入。

### 1.1.1 纯文本字符串

可以直接传入一个 `str`，该字符串会被视为待抽取的完整源文本。

```python
result = lx.extract(
    text_or_documents="Lady Juliet gazed longingly at the stars.",
    prompt_description=prompt,
    examples=examples,
    model_id="gemini-3.5-flash",
)
```

处理路径：

1. `extract()` 判断 `text_or_documents` 是字符串。
2. 构造内部 `Document`。
3. 使用 tokenizer 对文本进行 token 化。
4. 使用 `ChunkIterator` 按 `max_char_buffer` 分块。
5. 将每个 chunk 拼成 prompt，发送给语言模型。
6. 解析模型输出并对齐回源文本位置。

### 1.1.2 `Document` 对象集合

可以传入 `Iterable[data.Document]`，用于批量处理多个文本型文档。

`Document` 的核心字段为：

```python
Document(
    text: str,
    document_id: str | None = None,
    additional_context: str | None = None,
)
```

字段说明：

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `text` | `str` | 是 | 已解析好的源文本内容 |
| `document_id` | `str | None` | 否 | 文档 ID；未提供时自动生成 |
| `additional_context` | `str | None` | 否 | 文档级额外上下文，会补充到 prompt 中 |

示例：

```python
documents = [
    lx.data.Document(
        text="Alice founded Example Corp in 2020.",
        document_id="doc_001",
    ),
    lx.data.Document(
        text="Bob joined Example Corp as CTO.",
        document_id="doc_002",
    ),
]

results = lx.extract(
    text_or_documents=documents,
    prompt_description=prompt,
    examples=examples,
    model_id="gpt-4o-mini",
)
```

注意事项：

- `Document.text` 必须是文本，不是文件路径、二进制流或文件对象。
- 同一批次中的 `document_id` 应保持唯一。
- `additional_context` 适合放置文档来源、业务域、抽取规则补充等信息。

### 1.1.3 URL 文本下载输入

`extract()` 支持在特定条件下从 URL 下载文本：

```python
result = lx.extract(
    text_or_documents="https://example.com/file.txt",
    fetch_urls=True,
    prompt_description=prompt,
    examples=examples,
)
```

启用条件：

- `text_or_documents` 是字符串。
- 字符串是 `http://` 或 `https://` URL。
- 显式设置 `fetch_urls=True`。

处理限制：

- 下载逻辑位于 `io.download_text_from_url()`。
- 下载后只尝试按文本编码解码。
- 不执行 PDF、DOCX、HTML DOM、图片、音频或视频解析。
- 默认 `fetch_urls=False`，此时 URL 字符串会被当作普通文本处理。

安全注意：

- 源码注释明确提示 `fetch_urls=True` 存在 SSRF 风险。
- 服务化接入时，应只允许可信 URL，并在沙箱或隔离网络中执行。

### 1.1.4 CSV 数据集输入

`langextract.io.Dataset.load()` 支持从 CSV 读取文本数据，并生成 `Document` 迭代器。

支持条件：

- 文件后缀必须是 `.csv`。
- CSV 中必须包含指定的文本列和 ID 列。
- 读取实现基于 `pandas.read_csv()`。

字段配置：

```python
Dataset(
    input_path=Path("input.csv"),
    id_key="id",
    text_key="text",
)
```

输出为：

```python
Document(
    text=row[text_key],
    document_id=row[id_key],
)
```

限制：

- `Dataset.load()` 当前只支持 `.csv`。
- 非 CSV 文件会抛出 `NotImplementedError("Unsupported file type")`。
- CSV 中的文本列必须已经是可直接抽取的纯文本。

### 1.2 不支持的原始输入类型

当前 LangExtract 核心 pipeline 不直接支持以下原始文件或多模态输入：

| 类型 | 是否原生支持 | 说明 |
| --- | --- | --- |
| PDF | 否 | 无 PDF parser，未集成 `pypdf`、`pdfplumber`、`pymupdf` 等 |
| DOCX | 否 | 无 `python-docx` 或同类解析器 |
| XLSX | 否 | 仅看到 CSV 数据集读取，不支持 Excel 原始解析 |
| HTML DOM | 否 | URL 下载仅按文本解码，不进行网页正文抽取 |
| 图片 | 否 | 无 OCR 或图片输入接口 |
| 音频/视频 | 否 | 无 ASR 或媒体解析接口 |
| 向量数据 | 否 | 无 embedding 或向量索引输入 |
| 图数据 | 否 | 无图数据库或图结构输入 |

如果用于多模态 RAG 或 GraphRAG 系统，推荐在 LangExtract 前增加独立解析层：

```text
PDF/DOCX/图片/音频/网页/表格
  -> 文档解析 / OCR / ASR / 表格解析
  -> 统一文本或 Markdown
  -> langextract.extract()
  -> 结构化抽取结果
```

### 1.3 Prompt 和示例输入规范

`extract()` 要求提供 `examples`，否则会抛出错误。

示例结构为：

```python
lx.data.ExampleData(
    text="Marie Curie discovered radium.",
    extractions=[
        lx.data.Extraction(
            extraction_class="person",
            extraction_text="Marie Curie",
            attributes={"role": "scientist"},
        ),
        lx.data.Extraction(
            extraction_class="discovery",
            extraction_text="radium",
            attributes={"type": "chemical element"},
        ),
    ],
)
```

关键约束：

- `examples` 至少包含一个 `ExampleData`。
- `ExampleData.text` 是示例源文本。
- `Extraction.extraction_text` 最好是示例文本中的原文片段。
- `extraction_class` 定义抽取类别。
- `attributes` 可用于定义实体属性、关系属性或业务字段。
- LangExtract 会进行 prompt alignment 校验，帮助发现示例与源文本无法对齐的问题。

## 2. 文本模型接入规范

LangExtract 的模型抽象是 `BaseLanguageModel`，源码位于：

- `langextract_src/langextract/core/base_model.py`
- `langextract_src/langextract/factory.py`
- `langextract_src/langextract/providers/`

核心模型接口为：

```python
class BaseLanguageModel(abc.ABC):
    @abc.abstractmethod
    def infer(
        self,
        batch_prompts: Sequence[str],
        **kwargs,
    ) -> Iterator[Sequence[ScoredOutput]]:
        ...
```

这说明 LangExtract 当前接入的是文本生成模型接口：

```text
输入：Sequence[str] 文本 prompt
输出：Iterator[Sequence[ScoredOutput]]，其中 ScoredOutput.output 是模型生成的文本
```

### 2.1 模型接入方式

LangExtract 支持三种主要接入方式。

### 2.1.1 通过 `model_id` 自动路由

```python
result = lx.extract(
    text_or_documents=input_text,
    prompt_description=prompt,
    examples=examples,
    model_id="gemini-3.5-flash",
)
```

`factory.create_model()` 会根据 `model_id` 匹配 provider。

### 2.1.2 通过 `ModelConfig` 指定 provider

```python
from langextract.factory import ModelConfig

result = lx.extract(
    text_or_documents=input_text,
    prompt_description=prompt,
    examples=examples,
    config=ModelConfig(
        model_id="my-openai-compatible-model",
        provider="openai",
        provider_kwargs={
            "api_key": "...",
            "base_url": "https://example.com/v1",
        },
    ),
)
```

适用场景：

- 模型 ID 无法自动识别。
- 使用 OpenAI-compatible endpoint。
- 需要显式指定 Gemini、OpenAI、Ollama 或自定义 provider。

### 2.1.3 传入预配置模型对象

```python
model = SomeLanguageModel(...)

result = lx.extract(
    text_or_documents=input_text,
    prompt_description=prompt,
    examples=examples,
    model=model,
)
```

传入的模型对象应实现 `BaseLanguageModel.infer()`。

### 2.2 内置支持的模型类型

当前源码内置 provider 包括：

| Provider | 类 | 典型模型 | 外部依赖 |
| --- | --- | --- | --- |
| Gemini | `GeminiLanguageModel` | `gemini-3.5-flash` 等 Gemini 模型 | `google-genai`、API Key 或 Vertex AI |
| OpenAI | `OpenAILanguageModel` | `gpt-4o`、`gpt-4o-mini` 等 | 可选依赖 `openai`，需要 API Key |
| Ollama | `OllamaLanguageModel` | `gemma2:2b`、`llama3.x`、`mistral`、`qwen` 等本地模型 | 本地或远程 Ollama 服务 |

Provider 注册位于 `pyproject.toml`：

```toml
[project.entry-points."langextract.providers"]
gemini = "langextract.providers.gemini:GeminiLanguageModel"
ollama = "langextract.providers.ollama:OllamaLanguageModel"
openai = "langextract.providers.openai:OpenAILanguageModel"
```

### 2.3 Gemini 接入规范

Gemini provider 使用 `google-genai`。

认证方式：

- `api_key`
- 环境变量 `GEMINI_API_KEY`
- 环境变量 `LANGEXTRACT_API_KEY`
- Vertex AI：`vertexai=True`，并提供 `project`、`location`

示例：

```python
result = lx.extract(
    text_or_documents=input_text,
    prompt_description=prompt,
    examples=examples,
    model_id="gemini-3.5-flash",
    api_key="...",
)
```

Vertex AI 示例：

```python
result = lx.extract(
    text_or_documents=input_text,
    prompt_description=prompt,
    examples=examples,
    model_id="gemini-3.5-flash",
    language_model_params={
        "vertexai": True,
        "project": "your-project-id",
        "location": "global",
    },
)
```

结构化输出：

- Gemini provider 支持基于 examples 生成 schema。
- 当 `use_schema_constraints=True` 时，会尝试通过 provider schema 约束输出。

### 2.4 OpenAI 接入规范

OpenAI provider 使用 OpenAI Chat Completions 接口。

安装：

```bash
pip install langextract[openai]
```

认证方式：

- `api_key`
- 环境变量 `OPENAI_API_KEY`
- 环境变量 `LANGEXTRACT_API_KEY`

示例：

```python
result = lx.extract(
    text_or_documents=input_text,
    prompt_description=prompt,
    examples=examples,
    model_id="gpt-4o-mini",
)
```

OpenAI-compatible endpoint 示例：

```python
result = lx.extract(
    text_or_documents=input_text,
    prompt_description=prompt,
    examples=examples,
    config=ModelConfig(
        model_id="custom-model",
        provider="openai",
        provider_kwargs={
            "api_key": "...",
            "base_url": "https://your-compatible-endpoint/v1",
        },
    ),
)
```

结构化输出：

- JSON 模式下使用 `response_format`。
- 如果 provider schema 可用，会生成 OpenAI structured outputs schema。

### 2.5 Ollama 接入规范

Ollama provider 通过 HTTP 调用本地或远程 Ollama 服务。

默认地址：

```text
http://localhost:11434
```

示例：

```python
result = lx.extract(
    text_or_documents=input_text,
    prompt_description=prompt,
    examples=examples,
    model_id="gemma2:2b",
    model_url="http://localhost:11434",
)
```

前置条件：

- 已安装 Ollama。
- 已拉取目标模型，例如 `ollama pull gemma2:2b`。
- Ollama 服务可访问。

结构化输出：

- JSON 输出模式下会设置 Ollama 请求的 `format`。
- 对部分 reasoning 模型，LangExtract 默认设置 `think=False`，避免返回推理痕迹而不是最终 JSON。

### 2.6 自定义模型 Provider 接入规范

自定义 provider 应继承或兼容 `BaseLanguageModel`，至少实现：

```python
def infer(
    self,
    batch_prompts: Sequence[str],
    **kwargs,
) -> Iterator[Sequence[ScoredOutput]]:
    ...
```

最小要求：

- 输入必须接受批量文本 prompt。
- 输出必须是与输入 prompt 顺序对应的 `ScoredOutput` 序列。
- `ScoredOutput.output` 必须是可被 LangExtract resolver 解析的 JSON 或 YAML 文本。
- 如需自动 provider 发现，应通过 `langextract.providers` entry point 注册。

### 2.7 模型输出格式要求

模型输出必须能被 `Resolver` 解析为 JSON 或 YAML。

默认推荐 JSON 输出，结构通常为：

```json
{
  "extractions": [
    {
      "person": "Marie Curie",
      "person_attributes": {
        "role": "scientist"
      }
    }
  ]
}
```

输出中的字段会被解析为 `Extraction`：

- 普通字段名作为 `extraction_class`。
- 普通字段值作为 `extraction_text`。
- 以属性后缀结尾的字段作为 `attributes`，默认后缀为 `_attributes`。
- 可选 index 字段可用于排序，具体由 `resolver_params["extraction_index_suffix"]` 控制。

### 2.8 是否支持多模态模型

当前 pipeline 的模型接口是文本 prompt 接口，内置 provider 也是发送文本 prompt。

因此：

- 可以接入本身具备多模态能力的模型 ID。
- 但 LangExtract 当前不会向模型传递图片、音频、视频或 PDF binary。
- 对 LangExtract 而言，模型应被当作文本生成模型使用。

如果要使用多模态模型，应在 LangExtract 外部先完成多模态解析，得到文本或结构化文本后再进入 pipeline。

### 2.9 是否依赖 Embedding 模型

LangExtract 核心 pipeline 不依赖 embedding 模型。

源码中没有 embedding 生成、向量召回、向量数据库写入或相似度检索流程。Embedding 应由外部 RAG/GraphRAG 系统单独负责。

## 3. Pipeline 输出数据格式规范

LangExtract 的核心输出是：

```python
AnnotatedDocument
```

当输入为单个字符串时，返回：

```python
data.AnnotatedDocument
```

当输入为多个 `Document` 时，返回：

```python
list[data.AnnotatedDocument]
```

### 3.1 `AnnotatedDocument` 结构

源码定义：

```python
AnnotatedDocument(
    document_id: str | None = None,
    extractions: list[Extraction] | None = None,
    text: str | None = None,
)
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `document_id` | `str` | 文档 ID；未提供时自动生成 |
| `text` | `str | None` | 原始源文本 |
| `extractions` | `list[Extraction] | None` | 抽取结果列表 |
| `tokenized_text` | `TokenizedText | None` | 延迟生成的 token 化文本，不作为常规序列化主字段 |

### 3.2 `Extraction` 结构

源码定义的核心字段：

```python
Extraction(
    extraction_class: str,
    extraction_text: str,
    char_interval: CharInterval | None = None,
    alignment_status: AlignmentStatus | None = None,
    extraction_index: int | None = None,
    group_index: int | None = None,
    description: str | None = None,
    attributes: dict[str, str | list[str]] | None = None,
    token_interval: TokenInterval | None = None,
)
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `extraction_class` | `str` | 抽取类别，例如 `person`、`organization`、`relationship` |
| `extraction_text` | `str` | 抽取出的原文文本或模型输出文本 |
| `char_interval` | `CharInterval | None` | 抽取文本在源文本中的字符区间 |
| `token_interval` | `TokenInterval | None` | 抽取文本在 token 序列中的区间 |
| `alignment_status` | `AlignmentStatus | None` | 对齐状态 |
| `extraction_index` | `int | None` | 抽取顺序索引 |
| `group_index` | `int | None` | 模型输出中的分组索引 |
| `description` | `str | None` | 抽取项描述，默认通常为空 |
| `attributes` | `dict[str, str | list[str]] | None` | 属性字典 |

### 3.3 `CharInterval` 结构

```python
CharInterval(
    start_pos: int | None = None,
    end_pos: int | None = None,
)
```

语义：

- `start_pos`：字符起始位置，包含。
- `end_pos`：字符结束位置，不包含。
- 如果模型输出内容无法在源文本中定位，`char_interval` 可能为 `None`。

### 3.4 `TokenInterval` 结构

```python
TokenInterval(
    start_index: int,
    end_index: int,
)
```

语义：

- `start_index`：token 起始索引，包含。
- `end_index`：token 结束索引，不包含。
- 与内部 tokenizer 输出对应。

### 3.5 `AlignmentStatus` 枚举

对齐状态包括：

| 状态 | 说明 |
| --- | --- |
| `match_exact` | 完全 token 级匹配 |
| `match_greater` | 源码中定义的状态，表示匹配范围相对抽取结果更大 |
| `match_lesser` | 部分精确匹配，抽取文本比匹配文本更长 |
| `match_fuzzy` | 使用 fuzzy alignment 找到近似匹配 |
| `None` | 未对齐成功 |

服务化接入时，建议优先使用 `char_interval != None` 且 `alignment_status != None` 的结果作为可追溯抽取结果。

### 3.6 JSONL 序列化格式

LangExtract 支持将 `AnnotatedDocument` 保存为 JSON Lines：

```python
lx.io.save_annotated_documents(
    [result],
    output_name="extraction_results.jsonl",
    output_dir=".",
)
```

每一行是一个序列化后的 `AnnotatedDocument`。

示例：

```json
{
  "extractions": [
    {
      "extraction_class": "person",
      "extraction_text": "Marie Curie",
      "char_interval": {
        "start_pos": 0,
        "end_pos": 11
      },
      "alignment_status": "match_exact",
      "extraction_index": 1,
      "group_index": 0,
      "description": null,
      "attributes": {
        "role": "scientist"
      },
      "token_interval": {
        "start_index": 0,
        "end_index": 2
      }
    }
  ],
  "text": "Marie Curie discovered radium.",
  "document_id": "doc_001"
}
```

序列化特征：

- 枚举值会转换为字符串，例如 `AlignmentStatus.MATCH_EXACT` 转为 `"match_exact"`。
- NumPy integer 等整数类型会转换为普通 `int`。
- 内部字段名以下划线开头的属性不会写入 JSON。
- `token_interval` 和 `char_interval` 会作为嵌套对象输出。

### 3.7 JSONL 反序列化格式

读取 JSONL：

```python
documents = list(lx.io.load_annotated_documents_jsonl("extraction_results.jsonl"))
```

反序列化后恢复为：

```python
AnnotatedDocument(
    document_id=...,
    text=...,
    extractions=[Extraction(...)]
)
```

### 3.8 HTML 可视化输出

LangExtract 支持将抽取结果转换为 HTML 可视化：

```python
html_content = lx.visualize("extraction_results.jsonl")
```

或：

```python
html_content = lx.visualize(result)
```

输入要求：

- `AnnotatedDocument.text` 不能为空。
- `AnnotatedDocument.extractions` 不能为空。
- 只有带有效 `char_interval` 的 extraction 会参与高亮展示。

输出：

- 在 Jupyter 环境中返回 `IPython.display.HTML`。
- 非 Jupyter 环境中返回 HTML 字符串。

### 3.9 面向 RAG/GraphRAG 的输出使用建议

如果 LangExtract 作为多模态 RAG 或 GraphRAG 系统的数据抽取后端，建议将输出分为三类使用。

### 3.9.1 原文追溯字段

用于前端高亮、证据定位、审计：

- `document_id`
- `text`
- `char_interval`
- `token_interval`
- `alignment_status`

### 3.9.2 实体/关系字段

用于构建结构化知识：

- `extraction_class`
- `extraction_text`
- `attributes`
- `group_index`
- `extraction_index`

### 3.9.3 下游索引字段

LangExtract 不直接生成以下字段，但建议在下游补充：

- `source_file_id`
- `source_file_type`
- `page_number`
- `chunk_id`
- `chunk_text`
- `entity_id`
- `normalized_entity_name`
- `relation_type`
- `head_entity_id`
- `tail_entity_id`
- `embedding_id`
- `graph_node_id`
- `graph_edge_id`

推荐下游处理链路：

```text
AnnotatedDocument / JSONL
  -> 过滤未对齐或低可信 extraction
  -> 实体归一化与去重
  -> 关系建模
  -> 写入图数据库
  -> 文本块 embedding
  -> 写入向量数据库
  -> 构建 GraphRAG 检索与问答链路
```

## 4. 边界说明

LangExtract 当前应定位为文本结构化抽取组件，而不是完整 RAG/GraphRAG 框架。

它负责：

- 接收纯文本或文本型 `Document`。
- 按字符窗口和句子/token 边界分块。
- 调用文本生成模型抽取结构化信息。
- 将模型输出解析为 `Extraction`。
- 将抽取结果对齐回源文本位置。
- 输出 `AnnotatedDocument`、JSONL 或 HTML 可视化。

它不负责：

- 原始 PDF/DOCX/图片/音视频解析。
- OCR、ASR 或表格结构恢复。
- Embedding 生成。
- 向量索引。
- 图数据库建模和写入。
- 检索、rerank 或问答生成。
- HTTP API 服务封装。

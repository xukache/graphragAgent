"""将 MinerU content_list.json 转换为 LangExtract Document 列表。

设计依据：docs/mineru2langextract_handoff-v1.0.md 第 2、4、5 节。

策略：
- 按 page_idx 分组，每页生成一个 Document（策略 B）
- text 块：直接取文本；标题（text_level >= 1）前加 ## 作为分段
- table 块：HTML → Markdown 表格
- equation 块：保留 LaTeX
- image/chart 块：仅取 caption + footnote
- code 块：取 code_body
- list 块：list_items 拼接
- 辅助块（header/footer/page_number/aside_text/page_footnote）：跳过
- additional_context 携带块级元数据（type / bbox / text_level）供溯源
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import langextract as lx

from .table_parser import table_html_to_markdown


# 跳过的辅助块类型（无抽取价值）
SKIP_TYPES = {
    "header",
    "footer",
    "page_number",
    "aside_text",
    "page_footnote",
}


def convert_block_to_text(block: dict[str, Any]) -> str:
    """将单个 content_list 块转换为纯文本。返回空字符串表示跳过。"""
    btype = block.get("type", "")
    if btype in SKIP_TYPES:
        return ""

    if btype == "text":
        text = (block.get("text") or "").strip()
        if not text:
            return ""
        text_level = block.get("text_level")
        if isinstance(text_level, int) and text_level >= 1:
            # 标题：前加 ## 作为分段标记，便于 LLM 识别结构
            prefix = "#" * min(text_level + 1, 6)  # 一级标题 -> ##，二级 -> ###
            return f"{prefix} {text}"
        return text

    if btype == "table":
        body = block.get("table_body") or ""
        md = table_html_to_markdown(body)
        if not md:
            return ""
        # 表格前后加空行，并把 caption / footnote 一并带上
        parts = []
        captions = block.get("table_caption") or []
        footnotes = block.get("table_footnote") or []
        if captions:
            parts.append("**" + " ".join(c for c in captions if c) + "**")
        parts.append(md)
        if footnotes:
            parts.append("注：" + " ".join(f for f in footnotes if f))
        return "\n".join(parts)

    if btype == "equation":
        text = (block.get("text") or "").strip()
        if not text:
            return ""
        # MinerU 的 equation 已是 $$...$$ 形式，原样保留
        return text

    if btype in ("image", "chart"):
        captions = block.get("image_caption") or []
        footnotes = block.get("image_footnote") or []
        parts = []
        if captions:
            parts.append("[" + btype + " caption] " + " ".join(c for c in captions if c))
        if footnotes:
            parts.append("[" + btype + " footnote] " + " ".join(f for f in footnotes if f))
        return "\n".join(parts)

    if btype == "code":
        body = (block.get("code_body") or "").strip()
        if not body:
            return ""
        sub_type = block.get("sub_type", "code")
        return f"```{sub_type}\n{body}\n```"

    if btype == "list":
        items = block.get("list_items") or []
        if not items:
            # fallback 到 text
            return (block.get("text") or "").strip()
        return "\n".join(f"- {it}" for it in items if it)

    # 未知类型：尝试 text 字段，否则跳过
    return (block.get("text") or "").strip()


def _extract_block_meta(block: dict[str, Any]) -> dict[str, Any]:
    """提取块级元数据用于溯源。"""
    meta: dict[str, Any] = {
        "type": block.get("type"),
        "bbox": block.get("bbox"),
    }
    if "text_level" in block:
        meta["text_level"] = block["text_level"]
    if "img_path" in block:
        meta["img_path"] = block["img_path"]
    if "sub_type" in block:
        meta["sub_type"] = block["sub_type"]
    return meta


def content_list_to_documents(
    blocks: list[dict[str, Any]],
    source_file: str,
) -> list[lx.data.Document]:
    """按 page_idx 分组，每页生成一个 Document。

    Args:
        blocks: content_list.json 解析后的块列表
        source_file: 源文件名（用于 document_id 和 additional_context）

    Returns:
        list[Document]，按 page_idx 升序排列
    """
    if not blocks:
        return []

    # 按页分组
    pages: dict[int, list[dict[str, Any]]] = {}
    for block in blocks:
        page_idx = block.get("page_idx", 0)
        if not isinstance(page_idx, int):
            page_idx = 0
        pages.setdefault(page_idx, []).append(block)

    documents: list[lx.data.Document] = []
    for page_idx in sorted(pages.keys()):
        text_parts: list[str] = []
        block_meta: list[dict[str, Any]] = []

        for block in pages[page_idx]:
            converted = convert_block_to_text(block)
            if converted:
                text_parts.append(converted)
                block_meta.append(_extract_block_meta(block))

        if not text_parts:
            continue

        full_text = "\n\n".join(text_parts)
        ctx = json.dumps(
            {
                "source_file": source_file,
                "page_idx": page_idx,
                "blocks": block_meta,
            },
            ensure_ascii=False,
        )
        documents.append(
            lx.data.Document(
                text=full_text,
                document_id=f"{source_file}_page_{page_idx}",
                additional_context=ctx,
            )
        )

    return documents


def load_content_list(mineru_output_dir: Path) -> tuple[list[dict[str, Any]], str]:
    """从 mineru output 目录加载 content_list.json。

    用 glob 匹配 `*content_list.json`（避开 v2），不假设文件名前缀。

    Returns:
        (blocks, source_file)
    """
    candidates = [
        p
        for p in mineru_output_dir.glob("*content_list.json")
        if not p.name.endswith("_v2.json") and "v2" not in p.name
    ]
    if not candidates:
        raise FileNotFoundError(
            f"在 {mineru_output_dir} 下未找到 *content_list.json"
        )
    # 取最新修改的
    target = max(candidates, key=lambda p: p.stat().st_mtime)
    blocks = json.loads(target.read_text(encoding="utf-8"))

    # 尝试从 task_meta.json 读取 source 文件名，否则从 uuid 前缀推断
    meta_path = mineru_output_dir / "task_meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        source_file = meta.get("file_name") or target.stem
    else:
        source_file = target.stem.replace("_content_list", "")

    return blocks, source_file


if __name__ == "__main__":
    # 自测
    import sys

    target = (
        Path(sys.argv[1]) if len(sys.argv) > 1 else Path("../mineru_mvp/output")
    ).resolve()
    blocks, source = load_content_list(target)
    docs = content_list_to_documents(blocks, source)
    print(f"加载块数: {len(blocks)}, 生成 Document 数: {len(docs)}")
    for doc in docs:
        print(f"\n--- {doc.document_id} ---")
        print(f"text_len: {len(doc.text)}")
        print(f"text 预览:\n{doc.text[:300]}...")

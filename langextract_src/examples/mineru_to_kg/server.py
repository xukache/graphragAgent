"""GraphRAG Bridge Pipeline 可视化 Web 服务。

单文件后端：FastAPI + 内嵌 MinerU 调用 + LangExtract 抽取 + KG 构建。
前端：纯静态 HTML（index.html），通过 API 交互。

启动方式（在 langextract_src/.venv 内）：
    cd langextract_src
    uv run python -m examples.mineru_to_kg.server

设计依据：docs/index_pipeline_specification-v1.0.md
"""

from __future__ import annotations

import io
import json
import os
import tempfile
import time
import traceback
import zipfile
from pathlib import Path
from typing import Any

# 清理代理（DashScope + MinerU CDN 都是国内域名）
for _k in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
    os.environ.pop(_k, None)

import requests as http_requests
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import langextract as lx
from langextract.factory import ModelConfig

from .converter import content_list_to_documents
from .kg_builder import build_knowledge_graph
from .prompts import PROMPT, build_examples
from .table_parser import table_html_to_markdown

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

# 加载配置
_env_candidates = [BASE_DIR / ".env", BASE_DIR.parent / "qwen_mvp" / ".env"]
for p in _env_candidates:
    if p.exists():
        load_dotenv(p)
        break

app = FastAPI(title="GraphRAG Bridge Pipeline", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# --------------------------------------------------------------------------- #
# MinerU API 内联调用（从 mineru_pipeline.py 精简移植，避免跨 venv 依赖）
# --------------------------------------------------------------------------- #
def _mineru_headers() -> dict:
    token = os.getenv("MINERU_API_TOKEN", "").strip()
    if not token:
        raise RuntimeError("缺少 MINERU_API_TOKEN")
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "Accept": "*/*",
    }


def _mineru_parse(file_bytes: bytes, filename: str) -> dict:
    """调用 MinerU 精准解析 API，返回 content_list blocks。"""
    base = os.getenv("MINERU_API_BASE", "https://mineru.net/api/v4").strip()
    model_version = os.getenv("MINERU_MODEL_VERSION", "vlm").strip()
    headers = _mineru_headers()

    # 1. 申请上传链接
    payload = {
        "files": [{"name": filename, "is_ocr": False}],
        "model_version": model_version,
        "enable_table": True,
        "enable_formula": True,
        "language": "ch",
    }
    resp = http_requests.post(f"{base}/file-urls/batch", headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"MinerU 申请上传链接失败: {data.get('msg')}")
    batch_id = data["data"]["batch_id"]
    upload_url = data["data"]["file_urls"][0]

    # 2. PUT 上传
    put_resp = http_requests.put(upload_url, data=file_bytes, timeout=300)
    if put_resp.status_code != 200:
        raise RuntimeError(f"MinerU 文件上传失败: {put_resp.status_code}")

    # 3. 轮询
    poll_url = f"{base}/extract-results/batch/{batch_id}"
    deadline = time.time() + 600
    while time.time() < deadline:
        r = http_requests.get(poll_url, headers=headers, timeout=60)
        r.raise_for_status()
        result = r.json()
        if result.get("code") != 0:
            raise RuntimeError(f"MinerU 轮询失败: {result.get('msg')}")
        items = result["data"].get("extract_result", [])
        if items:
            state = items[0].get("state")
            if state == "done":
                zip_url = items[0]["full_zip_url"]
                break
            if state == "failed":
                raise RuntimeError(f"MinerU 解析失败: {items[0].get('err_msg')}")
        time.sleep(5)
    else:
        raise TimeoutError("MinerU 轮询超时")

    # 4. 下载并解压
    content = _download_zip(zip_url)
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        # 找 content_list.json
        cl_names = [n for n in zf.namelist() if n.endswith("content_list.json") and "v2" not in n]
        if not cl_names:
            raise RuntimeError("MinerU 结果中未找到 content_list.json")
        blocks = json.loads(zf.read(cl_names[0]))
    return blocks


def _download_zip(url: str) -> bytes:
    for attempt in range(4):
        proxies = None if attempt == 0 else {"http": None, "https": None}
        try:
            r = http_requests.get(url, timeout=300, proxies=proxies)
            r.raise_for_status()
            return r.content
        except Exception:
            if attempt >= 3:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("下载失败")


# --------------------------------------------------------------------------- #
# LangExtract 抽取（复用 mineru_to_kg 的逻辑）
# --------------------------------------------------------------------------- #
def _extract(blocks: list[dict], source_file: str) -> tuple[list[dict], dict]:
    """抽取 + 建图，返回 (flat_extractions, kg_json)。"""
    documents = content_list_to_documents(blocks, source_file)
    if not documents:
        return [], {"entities": [], "triples": [], "stats": {}}

    examples = build_examples()
    config = ModelConfig(
        model_id=os.getenv("QWEN_LLM_MODEL", "qwen3.7-max").strip(),
        provider="OpenAILanguageModel",
        provider_kwargs={
            "api_key": os.getenv("QWEN_API_KEY", "").strip(),
            "base_url": os.getenv("QWEN_API_BASE", "").strip(),
            "format_type": lx.data.FormatType.JSON,
            "temperature": 0.0,
            "max_workers": 4,
        },
    )

    # 重试
    results = None
    for attempt in range(3):
        results = lx.extract(
            text_or_documents=documents,
            prompt_description=PROMPT,
            examples=examples,
            config=config,
            use_schema_constraints=False,
            fence_output=True,
        )
        if not isinstance(results, list):
            results = [results]
        total = sum(len(r.extractions or []) for r in results)
        if total > 0:
            break
        time.sleep(2)

    # 扁平化
    flat: list[dict] = []
    for r in results:
        for ex in r.extractions or []:
            flat.append({
                "document_id": r.document_id,
                "extraction_class": ex.extraction_class,
                "extraction_text": ex.extraction_text,
                "attributes": ex.attributes,
                "char_interval": (
                    {"start_pos": ex.char_interval.start_pos, "end_pos": ex.char_interval.end_pos}
                    if ex.char_interval else None
                ),
                "alignment_status": ex.alignment_status.value if ex.alignment_status else None,
            })

    kg_json, _, _ = build_knowledge_graph(flat)
    return flat, kg_json


# --------------------------------------------------------------------------- #
# API 路由
# --------------------------------------------------------------------------- #
@app.post("/api/parse")
async def parse_pdf(file: UploadFile = File(...)):
    """上传 PDF → MinerU 解析 → LangExtract 抽取 → KG 构建，一站式返回。"""
    try:
        file_bytes = await file.read()
        filename = file.filename or "upload.pdf"

        # 阶段 1：MinerU 解析
        blocks = _mineru_parse(file_bytes, filename)

        # 阶段 2：LangExtract 抽取 + KG 构建
        extractions, kg = _extract(blocks, filename)

        return JSONResponse({
            "success": True,
            "filename": filename,
            "blocks_count": len(blocks),
            "extractions_count": len(extractions),
            "extractions": extractions,
            "knowledge_graph": kg,
        })
    except Exception as exc:
        return JSONResponse(
            {"success": False, "error": f"{type(exc).__name__}: {exc}", "detail": traceback.format_exc()},
            status_code=500,
        )


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


def main():
    STATIC_DIR.mkdir(exist_ok=True)
    print(f"GraphRAG Bridge Pipeline Web UI")
    print(f"  前端: http://localhost:8765")
    print(f"  API:  http://localhost:8765/api/parse (POST multipart/form-data)")
    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="info")


if __name__ == "__main__":
    main()

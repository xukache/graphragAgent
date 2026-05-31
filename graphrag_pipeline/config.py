"""Qwen LLM 配置（适配 LangChain 标准组件）。

依据 docs/langextract_specification-v1.0.md 的 Qwen via OpenAI-compatible 端点稳定组合：
- 必须显式 base_url 指向 DashScope
- temperature=0 保证抽取/分类稳定
- 用 ChatOpenAI 而非 init_chat_model（更直接，避免 model_id 路由问题）
- 启动前清理 *_PROXY 环境变量（DashScope 是国内域名）
"""

from __future__ import annotations

import os
from pathlib import Path

# DashScope 是国内域名，本机 SOCKS 代理会触发 SSL EOF
for _k in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
    os.environ.pop(_k, None)

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def get_llm(temperature: float = 0.0) -> ChatOpenAI:
    """返回配置好的 Qwen LLM（LangChain ChatOpenAI 接口）。"""
    api_key = os.getenv("QWEN_API_KEY", "").strip()
    api_base = os.getenv("QWEN_API_BASE", "").strip()
    model = os.getenv("QWEN_LLM_MODEL", "qwen3.7-max").strip()
    if not (api_key and api_base):
        raise RuntimeError("缺少 QWEN_API_KEY / QWEN_API_BASE，请检查 .env")
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=api_base,
        temperature=temperature,
        timeout=60,
        max_retries=2,
    )


def get_kg_path() -> Path:
    raw = os.getenv("KG_JSON_PATH", "").strip()
    if not raw:
        raise RuntimeError("缺少 KG_JSON_PATH")
    p = Path(raw)
    if not p.is_absolute():
        p = (BASE_DIR / p).resolve()
    if not p.exists():
        raise FileNotFoundError(f"KG 文件不存在: {p}")
    return p


def get_extractions_path() -> Path:
    raw = os.getenv("EXTRACTIONS_JSONL_PATH", "").strip()
    if not raw:
        return Path()
    p = Path(raw)
    if not p.is_absolute():
        p = (BASE_DIR / p).resolve()
    return p

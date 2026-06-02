"""配置加载（从 .env 文件读取）。"""
from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8000"))
DATA_DIR: Path = (BASE_DIR / os.getenv("DATA_DIR", "./data")).resolve()
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

QWEN_API_KEY: str = os.getenv("QWEN_API_KEY", "")
QWEN_API_BASE: str = os.getenv("QWEN_API_BASE", "")
QWEN_LLM_MODEL: str = os.getenv("QWEN_LLM_MODEL", "qwen3.7-max")

MINERU_VENV_PYTHON: str = os.getenv("MINERU_VENV_PYTHON", "")
LANGEXTRACT_VENV_PYTHON: str = os.getenv("LANGEXTRACT_VENV_PYTHON", "")

MAX_CONCURRENT_INDEX_JOBS: int = int(os.getenv("MAX_CONCURRENT_INDEX_JOBS", "2"))
MINERU_TIMEOUT_SECONDS: int = int(os.getenv("MINERU_TIMEOUT_SECONDS", "1800"))
LANGEXTRACT_TIMEOUT_SECONDS: int = int(os.getenv("LANGEXTRACT_TIMEOUT_SECONDS", "1800"))
AGENT_LRU_SIZE: int = int(os.getenv("AGENT_LRU_SIZE", "16"))
SESSION_HISTORY_LIMIT: int = int(os.getenv("SESSION_HISTORY_LIMIT", "20"))

# 文档存储目录
DOCUMENTS_DIR: Path = DATA_DIR / "documents"
DB_PATH: Path = DATA_DIR / "index.db"

# 确保目录存在
DATA_DIR.mkdir(parents=True, exist_ok=True)
DOCUMENTS_DIR.mkdir(parents=True, exist_ok=True)

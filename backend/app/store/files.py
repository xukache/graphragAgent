"""文档目录布局工具。"""
from __future__ import annotations
import shutil
from pathlib import Path
from app.config import DOCUMENTS_DIR


def doc_dir(document_id: str) -> Path:
    return DOCUMENTS_DIR / document_id

def source_path(document_id: str, ext: str) -> Path:
    return doc_dir(document_id) / f"source.{ext}"

def mineru_dir(document_id: str) -> Path:
    return doc_dir(document_id) / "mineru"

def kg_dir(document_id: str) -> Path:
    return doc_dir(document_id) / "kg"

def logs_dir(document_id: str) -> Path:
    return doc_dir(document_id) / "logs"

def kg_json_path(document_id: str) -> Path:
    return kg_dir(document_id) / "knowledge_graph.json"


def content_list_path(document_id: str) -> Path | None:
    """查找 mineru 产出的第一个 *content_list.json，找不到返回 None。"""
    mdir = mineru_dir(document_id)
    if not mdir.exists():
        return None
    files = list(mdir.glob("*content_list.json"))
    return files[0] if files else None

def ensure_doc_dirs(document_id: str) -> None:
    for d in [doc_dir(document_id), mineru_dir(document_id),
              kg_dir(document_id), logs_dir(document_id)]:
        d.mkdir(parents=True, exist_ok=True)

def delete_doc_dir(document_id: str) -> None:
    d = doc_dir(document_id)
    if d.exists():
        shutil.rmtree(d)

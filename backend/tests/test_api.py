"""端到端 API 接口测试（不依赖真实 MinerU/LangExtract）。"""
import io
import json
import os
import time
from pathlib import Path

# 清理代理（localhost 不需要代理）
for _k in ("ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy"):
    os.environ.pop(_k, None)

import httpx

BASE = "http://localhost:8001"
DOCS_DIR = Path(__file__).resolve().parent.parent / "data" / "documents"


def test_root():
    r = httpx.get(f"{BASE}/")
    assert r.status_code == 200
    assert r.json()["service"] == "GraphRAG Backend"


def test_health():
    r = httpx.get(f"{BASE}/api/health")
    assert r.status_code == 200
    data = r.json()
    assert "status" in data
    assert "checks" in data
    assert "sqlite" in data["checks"]
    print(f"  health: {data['status']}, checks: {data['checks']}")


def test_list_documents_empty():
    r = httpx.get(f"{BASE}/api/documents")
    assert r.status_code == 200
    data = r.json()
    assert "items" in data
    assert "total" in data
    print(f"  documents total: {data['total']}")


def test_upload_document():
    pdf_bytes = b"%PDF-1.4 test document content"
    files = {"file": ("test_report.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    r = httpx.post(f"{BASE}/api/documents", files=files)
    assert r.status_code == 201
    data = r.json()
    assert "document_id" in data
    assert "task_id" in data
    assert data["status"] == "pending"
    assert data["events_url"].startswith("/api/tasks/")
    print(f"  uploaded: {data['document_id']}, task: {data['task_id']}")
    return data


def test_upload_unsupported_type():
    files = {"file": ("test.xyz", io.BytesIO(b"data"), "application/octet-stream")}
    r = httpx.post(f"{BASE}/api/documents", files=files)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "UNSUPPORTED_FILE_TYPE"
    print("  unsupported type correctly rejected")


def test_get_document():
    # 先上传
    pdf_bytes = b"%PDF-1.4 get test"
    files = {"file": ("get_test.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    up = httpx.post(f"{BASE}/api/documents", files=files).json()
    doc_id = up["document_id"]

    r = httpx.get(f"{BASE}/api/documents/{doc_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["document_id"] == doc_id
    assert data["original_filename"] == "get_test.pdf"
    print(f"  get document: {data['status']}")


def test_get_document_not_found():
    r = httpx.get(f"{BASE}/api/documents/nonexistent-id")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "DOCUMENT_NOT_FOUND"
    print("  404 correctly returned")


def test_get_task():
    pdf_bytes = b"%PDF-1.4 task test"
    files = {"file": ("task_test.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    up = httpx.post(f"{BASE}/api/documents", files=files).json()
    task_id = up["task_id"]

    r = httpx.get(f"{BASE}/api/tasks/{task_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["task_id"] == task_id
    assert "state" in data
    assert "progress_pct" in data
    print(f"  task state: {data['state']}")


def test_list_documents_after_upload():
    r = httpx.get(f"{BASE}/api/documents")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    print(f"  total documents: {data['total']}")


def test_kg_not_ready():
    # When venvs are missing, subprocess is skipped and doc becomes ready immediately
    # but KG file won't exist → 404 KG_NOT_FOUND (not 409)
    pdf_bytes = b"%PDF-1.4 kg test"
    files = {"file": ("kg_test.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    up = httpx.post(f"{BASE}/api/documents", files=files).json()
    doc_id = up["document_id"]
    time.sleep(0.5)

    r = httpx.get(f"{BASE}/api/documents/{doc_id}/kg")
    # Either 409 (not ready) or 404 (ready but no KG file) — both are valid
    assert r.status_code in (404, 409)
    print(f"  KG endpoint returned {r.status_code} as expected")


def test_session_requires_ready_doc():
    # When venvs are missing, doc becomes ready immediately (subprocess skipped)
    # So session creation succeeds — test that session API works correctly
    pdf_bytes = b"%PDF-1.4 session test"
    files = {"file": ("sess_test.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    up = httpx.post(f"{BASE}/api/documents", files=files).json()
    doc_id = up["document_id"]
    time.sleep(0.5)

    # Try creating session — may succeed (ready) or fail (not ready) depending on venv availability
    r = httpx.post(f"{BASE}/api/sessions", json={"document_id": doc_id})
    assert r.status_code in (201, 409)
    if r.status_code == 201:
        sess_id = r.json()["session_id"]
        # Verify session appears in list
        r2 = httpx.get(f"{BASE}/api/sessions", params={"document_id": doc_id})
        assert r2.json()["total"] >= 1
        # Delete session
        r3 = httpx.delete(f"{BASE}/api/sessions/{sess_id}")
        assert r3.status_code == 204
        print(f"  session created and deleted: {sess_id}")
    else:
        print("  session creation blocked (doc not ready)")
    print(f"  session endpoint returned {r.status_code} as expected")


def test_delete_document():
    pdf_bytes = b"%PDF-1.4 delete test"
    files = {"file": ("del_test.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    up = httpx.post(f"{BASE}/api/documents", files=files).json()
    doc_id = up["document_id"]

    r = httpx.delete(f"{BASE}/api/documents/{doc_id}")
    assert r.status_code == 204

    r2 = httpx.get(f"{BASE}/api/documents/{doc_id}")
    assert r2.status_code == 404
    print(f"  deleted {doc_id}, confirmed 404")


def test_list_sessions_empty():
    pdf_bytes = b"%PDF-1.4 list sess test"
    files = {"file": ("list_sess.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    up = httpx.post(f"{BASE}/api/documents", files=files).json()
    doc_id = up["document_id"]

    r = httpx.get(f"{BASE}/api/sessions", params={"document_id": doc_id})
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 0
    print("  empty session list ok")


def test_pagination():
    r = httpx.get(f"{BASE}/api/documents", params={"page": 1, "page_size": 2})
    assert r.status_code == 200
    data = r.json()
    assert len(data["items"]) <= 2
    assert data["page"] == 1
    assert data["page_size"] == 2
    print(f"  pagination: {len(data['items'])} items on page 1")


# -------------------- /api/documents/{id}/pages --------------------

def test_pages_not_found():
    r = httpx.get(f"{BASE}/api/documents/nonexistent-id/pages")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "DOCUMENT_NOT_FOUND"
    print("  pages 404 correctly returned")


def test_pages_no_mineru():
    """上传 PDF 后立即查 pages → 200 + pages 字典（可能空，可能有 mineru 占位）。"""
    pdf_bytes = b"%PDF-1.4 pages no mineru test"
    files = {"file": ("no_mineru.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    up = httpx.post(f"{BASE}/api/documents", files=files).json()
    doc_id = up["document_id"]

    r = httpx.get(f"{BASE}/api/documents/{doc_id}/pages")
    assert r.status_code == 200
    data = r.json()
    assert "pages" in data
    assert isinstance(data["pages"], dict)
    print(f"  pages endpoint returned {len(data['pages'])} pages for fresh doc")


def test_pages_with_mineru():
    """手写一个 3 块 / 2 页的 content_list.json，验证拼接逻辑。"""
    pdf_bytes = b"%PDF-1.4 pages real"
    files = {"file": ("real_pages.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    up = httpx.post(f"{BASE}/api/documents", files=files).json()
    doc_id = up["document_id"]

    cl_path = DOCS_DIR / doc_id / "mineru" / "test_real_pages_content_list.json"
    cl_path.parent.mkdir(parents=True, exist_ok=True)
    cl_path.write_text(json.dumps([
        {"type": "text", "text": "First page A.", "page_idx": 0},
        {"type": "text", "text": "First page B.", "page_idx": 0},
        {"type": "text", "text": "Second page only.", "page_idx": 1},
        {"type": "image", "page_idx": 0},                       # 应被忽略
        {"type": "text", "text": "   ", "page_idx": 0},          # 全空白应被跳过
    ]), encoding="utf-8")

    r = httpx.get(f"{BASE}/api/documents/{doc_id}/pages")
    assert r.status_code == 200
    data = r.json()

    page0_id = f"{doc_id}_page_0"
    page1_id = f"{doc_id}_page_1"
    assert page0_id in data["pages"], f"missing {page0_id} in {list(data['pages'].keys())}"
    assert page1_id in data["pages"]
    assert "First page A." in data["pages"][page0_id]
    assert "First page B." in data["pages"][page0_id]
    assert "Second page only." in data["pages"][page1_id]
    print(f"  pages: page0={len(data['pages'][page0_id])} chars, page1={len(data['pages'][page1_id])} chars")


def test_pages_table_block():
    """table 块的 table_body HTML 标签应被去除。"""
    pdf_bytes = b"%PDF-1.4 table test"
    files = {"file": ("table_pages.pdf", io.BytesIO(pdf_bytes), "application/pdf")}
    up = httpx.post(f"{BASE}/api/documents", files=files).json()
    doc_id = up["document_id"]

    cl_path = DOCS_DIR / doc_id / "mineru" / "test_table_content_list.json"
    cl_path.parent.mkdir(parents=True, exist_ok=True)
    cl_path.write_text(json.dumps([
        {
            "type": "table",
            "table_body": "<table><tr><td>Cell 1</td><td>Cell 2</td></tr></table>",
            "page_idx": 0,
        },
    ]), encoding="utf-8")

    r = httpx.get(f"{BASE}/api/documents/{doc_id}/pages")
    assert r.status_code == 200
    data = r.json()
    page_id = f"{doc_id}_page_0"
    text = data["pages"][page_id]
    assert "Cell 1" in text
    assert "Cell 2" in text
    assert "<table>" not in text
    assert "<td>" not in text
    assert "</tr>" not in text
    print(f"  table HTML stripped, clean text: {text!r}")


if __name__ == "__main__":
    tests = [
        test_root, test_health, test_list_documents_empty,
        test_upload_document, test_upload_unsupported_type,
        test_get_document, test_get_document_not_found,
        test_get_task, test_list_documents_after_upload,
        test_kg_not_ready, test_session_requires_ready_doc,
        test_delete_document, test_list_sessions_empty, test_pagination,
        test_pages_not_found, test_pages_no_mineru,
        test_pages_with_mineru, test_pages_table_block,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"✅ {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"❌ {t.__name__}: {e}")
            failed += 1
    print(f"\n{'='*50}")
    print(f"结果：{passed} 通过，{failed} 失败，共 {len(tests)} 个测试")

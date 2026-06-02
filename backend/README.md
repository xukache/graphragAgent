# GraphRAG Backend

多模态知识问答系统后端服务（FastAPI + SQLite + SSE）。

## 启动

```bash
cd /path/to/graphragAgent
uv run --project backend uvicorn app.main:app --host 0.0.0.0 --port 8000
# 开发模式
uv run --project backend uvicorn app.main:app --reload --port 8000
```

## 接口文档

启动后访问 http://localhost:8000/docs

## 测试

```bash
cd backend
uv run python tests/test_api.py
```

## 配置

所有配置在 `backend/.env`，参见 `.env` 文件注释。

## 规范

详见 `docs/graphrag_backend_specification-v1.0.md`。

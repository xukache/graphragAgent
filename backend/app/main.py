"""FastAPI 应用入口。"""
from __future__ import annotations
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import LOG_LEVEL
from app.store.db import init_db
from app.routers import documents, tasks, sessions, health

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO))

app = FastAPI(
    title="GraphRAG Backend",
    version="0.1.0",
    description="多模态知识问答系统后端服务",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup():
    init_db()
    logging.getLogger(__name__).info("GraphRAG Backend started, DB initialized.")


app.include_router(documents.router)
app.include_router(tasks.router)
app.include_router(sessions.router)
app.include_router(health.router)


@app.get("/")
def root():
    return {"service": "GraphRAG Backend", "version": "0.1.0", "docs": "/docs"}

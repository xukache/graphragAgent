import { useState, useCallback, useEffect, useRef } from 'react';
import { TopBar } from './components/TopBar';
import { Sidebar } from './components/Sidebar';
import { ChatPanel } from './components/ChatPanel';
import { IndexProgress } from './components/IndexProgress';
import type { IndexProgressProps, StageState as StageStateType } from './components/IndexProgress';
import { KGPanel } from './components/KGPanel';
import { UploadOverlay } from './components/UploadOverlay';
import { Document, Session, Message, KGData, Source, DrawerSource } from './types';
import {
  listDocuments,
  uploadDocument,
  deleteDocument,
  getDocument,
  getKG,
  getDocumentPages,
  subscribeTaskEvents,
  listSessions,
  createSession,
  deleteSession as apiDeleteSession,
  listMessages,
  streamChat,
  getHealth,
  ApiError,
} from './api';

interface IndexingState {
  parsing: StageStateType;
  extracting: StageStateType;
  building_kg: StageStateType;
}

const STAGE_ORDER: Array<keyof IndexingState> = ['parsing', 'extracting', 'building_kg'];
// 与 backend/app/orchestrator/job.py 一致的权重，用于把后端的总进度还原到当前阶段的局部进度
const STAGE_BASE: Record<keyof IndexingState, number> = { parsing: 0, extracting: 40, building_kg: 90 };
const STAGE_WEIGHT: Record<keyof IndexingState, number> = { parsing: 40, extracting: 50, building_kg: 10 };

const initialIndexing = (active: keyof IndexingState = 'parsing'): IndexingState => {
  const out: IndexingState = {
    parsing: { status: 'waiting', progress: 0 },
    extracting: { status: 'waiting', progress: 0 },
    building_kg: { status: 'waiting', progress: 0 },
  };
  out[active] = { status: 'active', progress: 0 };
  return out;
};

function isIndexing(status: Document['status']): boolean {
  return status === 'pending' || status === 'parsing' || status === 'extracting' || status === 'building_kg';
}

/** 索引中或失败 — 都让 IndexProgress 占据中间区域（失败时用于展示错误）。 */
function shouldShowIndexProgress(status: Document['status']): boolean {
  return isIndexing(status) || status === 'failed';
}

export default function App() {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messagesBySession, setMessagesBySession] = useState<Record<string, Message[]>>({});
  const [kgByDoc, setKgByDoc] = useState<Record<string, KGData>>({});
  const [indexingStates, setIndexingStates] = useState<Record<string, IndexingState>>({});
  const [isStreaming, setIsStreaming] = useState(false);
  const [highlightedIds, setHighlightedIds] = useState<string[]>([]);
  const [focusEntityIds, setFocusEntityIds] = useState<string[]>([]);
  const [pageTextByDoc, setPageTextByDoc] = useState<Record<string, Record<string, string>>>({});
  const [drawerSource, setDrawerSource] = useState<DrawerSource | null>(null);
  const [showUpload, setShowUpload] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [kgCollapsed, setKgCollapsed] = useState(false);
  const [healthy, setHealthy] = useState(true);
  const [bootError, setBootError] = useState<string | null>(null);

  const sseClosersRef = useRef<Record<string, () => void>>({});
  const streamAbortRef = useRef<AbortController | null>(null);

  const selectedDoc = documents.find((d) => d.id === selectedDocId) ?? null;
  const currentMessages = activeSessionId ? messagesBySession[activeSessionId] ?? [] : [];
  const currentKg = selectedDocId ? kgByDoc[selectedDocId] ?? null : null;

  /* ---------- 启动：拉文档列表 + 健康检查 ---------- */
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [docs, h] = await Promise.all([listDocuments(), getHealth().catch(() => null)]);
        if (cancelled) return;
        setDocuments(docs);
        if (h) setHealthy(h.status === 'ok');
        // 默认选第一个 ready 的文档；若没有则选第一个
        const firstReady = docs.find((d) => d.status === 'ready') ?? docs[0] ?? null;
        if (firstReady) setSelectedDocId(firstReady.id);
        // 重新订阅仍在索引中的文档（页面刷新后恢复）
        for (const d of docs) {
          if (isIndexing(d.status)) {
            const detail = await getDocument(d.id).catch(() => null);
            const taskId = detail?.id ? null : null; // 后端 GET /documents/{id} 含 current_task；但此处简化
            // current_task 的 task_id 没暴露在 UiDocument 中，省略恢复订阅；用户若刷新会丢失实时进度，
            // 但状态会通过定期 getDocument 兜底。此处直接置一个 active 状态占位。
            setIndexingStates((prev) => ({ ...prev, [d.id]: initialIndexing('parsing') }));
          }
        }
      } catch (err) {
        const msg = err instanceof ApiError ? err.message : String(err);
        setBootError(`无法连接后端 (${msg})。请确认 backend 已在 :8000 启动。`);
        setHealthy(false);
      }
    })();
    return () => {
      cancelled = true;
      // 关掉所有 SSE
      Object.values(sseClosersRef.current).forEach((fn) => fn());
      sseClosersRef.current = {};
      streamAbortRef.current?.abort();
    };
  }, []);

  /* ---------- 选中文档变化：拉会话 + KG ---------- */
  useEffect(() => {
    if (!selectedDocId) {
      setSessions([]);
      setActiveSessionId(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const docSessions = await listSessions(selectedDocId);
        if (cancelled) return;
        setSessions((prev) => {
          // 保留其他文档的会话
          const others = prev.filter((s) => s.documentId !== selectedDocId);
          return [...others, ...docSessions];
        });
        if (docSessions.length > 0) {
          setActiveSessionId(docSessions[0].id);
        } else {
          // 文档已就绪但还没有任何会话：自动建一个，保证输入框有归属
          const doc = documents.find((d) => d.id === selectedDocId);
          if (doc && doc.status === 'ready') {
            try {
              const sess = await createSession(selectedDocId);
              if (cancelled) return;
              setSessions((prev) => [...prev, sess]);
              setActiveSessionId(sess.id);
              setMessagesBySession((prev) => ({ ...prev, [sess.id]: [] }));
            } catch {
              setActiveSessionId(null);
            }
          } else {
            setActiveSessionId(null);
          }
        }
      } catch {
        // 文档未就绪时后端会 409；忽略
      }

      // KG + Pages（只在 ready 且确认有 kg_stats 时拉，避免老脏数据触发 404）
      const doc = documents.find((d) => d.id === selectedDocId);
      if (doc && doc.status === 'ready' && doc.kg && !kgByDoc[selectedDocId]) {
        try {
          const [kg, pages] = await Promise.all([
            getKG(selectedDocId),
            getDocumentPages(selectedDocId).catch(() => ({})),
          ]);
          if (!cancelled) {
            setKgByDoc((prev) => ({ ...prev, [selectedDocId]: kg }));
            setPageTextByDoc((prev) => ({ ...prev, [selectedDocId]: pages }));
          }
        } catch {
          // KG 文件可能尚未写盘或被外部删除
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [selectedDocId, documents]);

  /* ---------- 切换会话：拉历史消息 ---------- */
  useEffect(() => {
    if (!activeSessionId || messagesBySession[activeSessionId] !== undefined) return;
    (async () => {
      try {
        const msgs = await listMessages(activeSessionId);
        setMessagesBySession((prev) => ({ ...prev, [activeSessionId]: msgs }));
      } catch {
        setMessagesBySession((prev) => ({ ...prev, [activeSessionId]: [] }));
      }
    })();
  }, [activeSessionId]);  // eslint-disable-line react-hooks/exhaustive-deps

  /* ---------- 索引进度：处理后端 SSE 事件 ---------- */
  const applyProgress = useCallback((docId: string, stage: keyof IndexingState, overallPct: number, detail?: string) => {
    const base = STAGE_BASE[stage];
    const weight = STAGE_WEIGHT[stage];
    const local = Math.max(0, Math.min(100, Math.round(((overallPct - base) / weight) * 100)));

    setIndexingStates((prev) => {
      const cur = prev[docId] ?? initialIndexing(stage);
      const next: IndexingState = { ...cur };
      // 把更早的阶段置为 done
      for (const s of STAGE_ORDER) {
        if (s === stage) {
          next[s] = { ...cur[s], status: 'active', progress: local, detail };
        } else if (STAGE_ORDER.indexOf(s) < STAGE_ORDER.indexOf(stage)) {
          if (cur[s].status !== 'done') next[s] = { ...cur[s], status: 'done', progress: 100 };
        }
      }
      return { ...prev, [docId]: next };
    });

    setDocuments((prev) =>
      prev.map((d) => (d.id === docId ? { ...d, status: stage as Document['status'], progress: overallPct } : d))
    );
  }, []);

  const subscribeToTask = useCallback(
    (docId: string, taskId: string) => {
      // 旧订阅清掉
      sseClosersRef.current[docId]?.();
      const close = subscribeTaskEvents(taskId, {
        onStageStart: (stage) => {
          if (STAGE_ORDER.includes(stage as any)) {
            applyProgress(docId, stage as keyof IndexingState, STAGE_BASE[stage as keyof IndexingState]);
          }
        },
        onProgress: (stage, pct, detail) => {
          if (STAGE_ORDER.includes(stage as any)) {
            applyProgress(docId, stage as keyof IndexingState, pct, detail);
          }
        },
        onStageDone: (stage, elapsedMs) => {
          if (!STAGE_ORDER.includes(stage as any)) return;
          setIndexingStates((prev) => {
            const cur = prev[docId];
            if (!cur) return prev;
            const next: IndexingState = { ...cur };
            next[stage as keyof IndexingState] = {
              status: 'done',
              progress: 100,
              elapsed: elapsedMs / 1000,
            };
            return { ...prev, [docId]: next };
          });
        },
        onComplete: async (entityCount, tripleCount) => {
          // 关闭流
          sseClosersRef.current[docId]?.();
          delete sseClosersRef.current[docId];
          // 全部 done
          setIndexingStates((prev) => {
            const cur = prev[docId] ?? initialIndexing('building_kg');
            return {
              ...prev,
              [docId]: {
                parsing: { ...cur.parsing, status: 'done', progress: 100 },
                extracting: { ...cur.extracting, status: 'done', progress: 100 },
                building_kg: { ...cur.building_kg, status: 'done', progress: 100 },
              },
            };
          });
          setDocuments((prev) =>
            prev.map((d) =>
              d.id === docId
                ? {
                    ...d,
                    status: 'ready',
                    progress: 100,
                    kg: entityCount != null && tripleCount != null
                      ? { entities: entityCount, relations: tripleCount }
                      : d.kg,
                  }
                : d
            )
          );
          // 拉 KG
          try {
            const kg = await getKG(docId);
            setKgByDoc((prev) => ({ ...prev, [docId]: kg }));
          } catch { /* 忽略 */ }
          // 自动建一个会话
          try {
            const sess = await createSession(docId);
            setSessions((prev) => [...prev, sess]);
            if (selectedDocId === docId) setActiveSessionId(sess.id);
            setMessagesBySession((prev) => ({ ...prev, [sess.id]: [] }));
          } catch { /* 忽略 */ }
        },
        onError: (stage, message) => {
          sseClosersRef.current[docId]?.();
          delete sseClosersRef.current[docId];
          setIndexingStates((prev) => {
            const cur = prev[docId] ?? initialIndexing();
            const target = (STAGE_ORDER.includes(stage as any) ? stage : 'parsing') as keyof IndexingState;
            return {
              ...prev,
              [docId]: { ...cur, [target]: { ...cur[target], status: 'error', error: message } },
            };
          });
          setDocuments((prev) =>
            prev.map((d) => (d.id === docId ? { ...d, status: 'failed', error: message } : d))
          );
        },
      });
      sseClosersRef.current[docId] = close;
    },
    [applyProgress, selectedDocId]
  );

  /* ---------- 操作：上传 ---------- */
  const handleUpload = useCallback(
    async (file: File) => {
      try {
        const { document, taskId } = await uploadDocument(file);
        setDocuments((prev) => [document, ...prev]);
        setSelectedDocId(document.id);
        setIndexingStates((prev) => ({ ...prev, [document.id]: initialIndexing('parsing') }));
        setShowUpload(false);
        subscribeToTask(document.id, taskId);
      } catch (err) {
        const msg = err instanceof ApiError ? err.message : String(err);
        alert(`上传失败：${msg}`);
      }
    },
    [subscribeToTask]
  );

  /* ---------- 操作：删除文档 ---------- */
  const handleDeleteDoc = useCallback(
    async (docId: string) => {
      try {
        await deleteDocument(docId);
      } catch (err) {
        const msg = err instanceof ApiError ? err.message : String(err);
        alert(`删除失败：${msg}`);
        return;
      }
      sseClosersRef.current[docId]?.();
      delete sseClosersRef.current[docId];
      setDocuments((prev) => prev.filter((d) => d.id !== docId));
      setSessions((prev) => prev.filter((s) => s.documentId !== docId));
      setKgByDoc((prev) => {
        const next = { ...prev };
        delete next[docId];
        return next;
      });
      setPageTextByDoc((prev) => {
        const next = { ...prev };
        delete next[docId];
        return next;
      });
      setIndexingStates((prev) => {
        const next = { ...prev };
        delete next[docId];
        return next;
      });
      if (selectedDocId === docId) {
        setSelectedDocId((prev) => {
          const remaining = documents.filter((d) => d.id !== docId);
          return remaining.length > 0 ? remaining[0].id : null;
        });
        setActiveSessionId(null);
      }
    },
    [selectedDocId, documents]
  );

  /* ---------- 操作：切换文档 ---------- */
  const handleSelectDoc = useCallback((docId: string) => {
    setSelectedDocId(docId);
    setHighlightedIds([]);
    setFocusEntityIds([]);
    setDrawerSource(null);
  }, []);

  /* ---------- 操作：会话 ---------- */
  const handleNewSession = useCallback(async () => {
    if (!selectedDocId) return;
    try {
      const sess = await createSession(selectedDocId);
      setSessions((prev) => [...prev, sess]);
      setActiveSessionId(sess.id);
      setMessagesBySession((prev) => ({ ...prev, [sess.id]: [] }));
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : String(err);
      alert(`新建会话失败：${msg}`);
    }
  }, [selectedDocId]);

  const handleDeleteSession = useCallback(
    async (sessId: string) => {
      try {
        await apiDeleteSession(sessId);
      } catch {
        // 忽略
      }
      setSessions((prev) => prev.filter((s) => s.id !== sessId));
      setMessagesBySession((prev) => {
        const next = { ...prev };
        delete next[sessId];
        return next;
      });
      if (activeSessionId === sessId) {
        const remain = sessions.filter((s) => s.documentId === selectedDocId && s.id !== sessId);
        setActiveSessionId(remain.length > 0 ? remain[0].id : null);
      }
    },
    [activeSessionId, selectedDocId, sessions]
  );

  /* ---------- 操作：发送消息（流式） ---------- */
  const handleSendMessage = useCallback(
    async (text: string) => {
      if (isStreaming) return;

      // 没有活动会话时（例如打开一个旧的 ready 文档但尚无会话），先自动建一个，
      // 避免消息被静默丢弃。
      let sessionId = activeSessionId;
      if (!sessionId) {
        if (!selectedDocId) return;
        const doc = documents.find((d) => d.id === selectedDocId);
        if (!doc || doc.status !== 'ready') return;
        try {
          const sess = await createSession(selectedDocId);
          sessionId = sess.id;
          setSessions((prev) => [...prev, sess]);
          setActiveSessionId(sess.id);
          setMessagesBySession((prev) => ({ ...prev, [sess.id]: [] }));
        } catch (err) {
          const msg = err instanceof ApiError ? err.message : String(err);
          alert(`无法创建会话：${msg}`);
          return;
        }
      }

      const userMsg: Message = { id: `tmp-u-${Date.now()}`, role: 'user', content: text };
      const assistantMsgId = `tmp-a-${Date.now()}`;
      const assistantMsg: Message = {
        id: assistantMsgId,
        role: 'assistant',
        content: '',
        isStreaming: true,
        toolCalls: [],
      };

      setMessagesBySession((prev) => ({
        ...prev,
        [sessionId!]: [...(prev[sessionId!] ?? []), userMsg, assistantMsg],
      }));
      setIsStreaming(true);

      const ac = new AbortController();
      streamAbortRef.current = ac;

      const toolNames: string[] = [];
      const t0 = Date.now();
      let aborted = false;

      try {
        await streamChat(
          sessionId!,
          text,
          {
            onToolCall: (name) => {
              toolNames.push(name);
              setMessagesBySession((prev) => ({
                ...prev,
                [sessionId!]: (prev[sessionId!] ?? []).map((m) =>
                  m.id === assistantMsgId
                    ? {
                        ...m,
                        toolCalls: toolNames.map((n, i) => ({
                          name: n,
                          status: i < toolNames.length - 1 ? 'done' : 'calling',
                        })),
                      }
                    : m
                ),
              }));
            },
            onToken: (chunk) => {
              setMessagesBySession((prev) => ({
                ...prev,
                [sessionId!]: (prev[sessionId!] ?? []).map((m) => {
                  if (m.id !== assistantMsgId) return m;
                  // 收到第一个 token 时，把所有 tool 标为 done
                  const tcs = m.toolCalls?.map((t) => ({ ...t, status: 'done' as const }));
                  return { ...m, content: m.content + chunk, isStreaming: true, toolCalls: tcs };
                }),
              }));
            },
            onComplete: ({ messageId, answer, toolCalls, latencyMs, entityIds }) => {
              // 把 entity_ids 展开为 Message.sources：每个 entity 的 sources[] 拍平
              const nodeMap = new Map(
                (currentKg?.nodes ?? []).map((n) => [n.id, n])
              );
              const sources: Source[] = (entityIds ?? []).flatMap((eid) => {
                const node = nodeMap.get(eid);
                if (!node) return [];
                return (node.sources ?? []).map((s) => ({
                  entityId: eid,
                  documentId: s.documentId,
                  location: s.documentId,   // 后端 page_id 格式: {doc_id}_page_{idx}
                  text: node.label,
                  charInterval: s.charInterval,
                  entityLabel: node.label,
                  entityClass: node.entityClass,
                }));
              });

              setMessagesBySession((prev) => ({
                ...prev,
                [sessionId!]: (prev[sessionId!] ?? []).map((m) =>
                  m.id === assistantMsgId
                    ? {
                        ...m,
                        id: messageId,
                        content: answer,
                        isStreaming: false,
                        elapsed: latencyMs / 1000,
                        toolCalls: toolCalls.map((n) => ({ name: n, status: 'done' as const })),
                        sources: sources.length > 0 ? sources : undefined,
                      }
                    : m
                ),
              }));
              // 高亮 + 聚焦实际用到的 KG 节点（从工具调用参数 + 回答文本中提取）
              if (entityIds.length > 0) {
                setHighlightedIds(entityIds);
                setFocusEntityIds(entityIds);
                setTimeout(() => setHighlightedIds([]), 4000);
              }
            },
            onError: (msg) => {
              aborted = true;
              setMessagesBySession((prev) => ({
                ...prev,
                [sessionId!]: (prev[sessionId!] ?? []).map((m) =>
                  m.id === assistantMsgId
                    ? { ...m, content: msg || '回答失败', isStreaming: false, isError: true }
                    : m
                ),
              }));
            },
          },
          ac.signal
        );
      } catch (err) {
        aborted = true;
        const msg = err instanceof ApiError ? err.message : String(err);
        setMessagesBySession((prev) => ({
          ...prev,
          [sessionId!]: (prev[sessionId!] ?? []).map((m) =>
            m.id === assistantMsgId
              ? { ...m, content: msg, isStreaming: false, isError: true }
              : m
          ),
        }));
      } finally {
        setIsStreaming(false);
        if (!aborted && Date.now() - t0 < 200) {
          // 后端立即关流且没产出任何内容时，至少把 streaming 关掉
          setMessagesBySession((prev) => ({
            ...prev,
            [sessionId!]: (prev[sessionId!] ?? []).map((m) =>
              m.id === assistantMsgId ? { ...m, isStreaming: false } : m
            ),
          }));
        }
      }
    },
    [activeSessionId, isStreaming, currentKg, selectedDocId, documents]
  );

  const handleRetry = useCallback(() => {
    if (!activeSessionId) return;
    const msgs = messagesBySession[activeSessionId] ?? [];
    const lastUser = [...msgs].reverse().find((m) => m.role === 'user');
    if (!lastUser) return;
    // 移除失败的 assistant 消息后重发（注意：用户消息已在后端入库，会重复，属于已知限制）
    setMessagesBySession((prev) => ({
      ...prev,
      [activeSessionId]: msgs.filter((m) => !m.isError),
    }));
    handleSendMessage(lastUser.content);
  }, [activeSessionId, messagesBySession, handleSendMessage]);

  const showIndexProgress =
    selectedDoc && shouldShowIndexProgress(selectedDoc.status);

  const indexingForCurrentDoc = selectedDocId ? indexingStates[selectedDocId] : null;

  // failed 时，把错误注入到当前正在跑的（或第一个非 done 的）阶段
  const indexProgressProps: IndexProgressProps | null =
    showIndexProgress && selectedDoc
      ? (() => {
          let stages = indexingForCurrentDoc ?? initialIndexing();
          if (selectedDoc.status === 'failed' && selectedDoc.error) {
            const target = (['parsing', 'extracting', 'building_kg'] as const).find(
              (s) => stages[s].status !== 'done'
            ) ?? 'parsing';
            stages = {
              ...stages,
              [target]: { ...stages[target], status: 'error', error: selectedDoc.error },
            };
          }
          return { docName: selectedDoc.name, stages };
        })()
      : null;

  return (
    <div
      style={{
        width: '100%',
        height: '100%',
        background: 'oklch(0.12 0.008 260)',
        display: 'flex',
        flexDirection: 'column',
        fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif',
        fontSize: 13,
        color: 'oklch(0.92 0.005 260)',
        overflow: 'hidden',
      }}
    >
      <TopBar healthy={healthy} />

      {bootError && (
        <div
          style={{
            padding: '6px 16px',
            background: 'oklch(0.22 0.04 25)',
            color: 'oklch(0.85 0.1 25)',
            fontSize: 12,
            borderBottom: '1px solid oklch(0.62 0.18 25 / 0.3)',
          }}
        >
          {bootError}
        </div>
      )}

      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative' }}>
        <Sidebar
          documents={documents}
          selectedDocId={selectedDocId}
          collapsed={sidebarCollapsed}
          onSelectDoc={handleSelectDoc}
          onDeleteDoc={handleDeleteDoc}
          onUploadClick={() => setShowUpload(true)}
          onToggleCollapse={() => setSidebarCollapsed((v) => !v)}
        />

        {/* Center panel */}
        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            minWidth: 400,
            overflow: 'hidden',
            background: 'oklch(0.12 0.008 260)',
          }}
        >
          {indexProgressProps ? (
            <IndexProgress {...indexProgressProps} />
          ) : (
            <ChatPanel
              document={selectedDoc}
              sessions={sessions}
              activeSessionId={activeSessionId}
              messages={currentMessages}
              isStreaming={isStreaming}
              onSendMessage={handleSendMessage}
              onNewSession={handleNewSession}
              onSelectSession={(id) => { setActiveSessionId(id); setFocusEntityIds([]); }}
              onDeleteSession={handleDeleteSession}
              onRetry={handleRetry}
            />
          )}
        </div>

        <KGPanel
          data={currentKg}
          highlightedIds={highlightedIds}
          focusIds={focusEntityIds}
          collapsed={kgCollapsed}
          onToggleCollapse={() => setKgCollapsed((v) => !v)}
        />
      </div>

      {showUpload && (
        <UploadOverlay onClose={() => setShowUpload(false)} onUpload={handleUpload} />
      )}
    </div>
  );
}

/**
 * 高层 API + UI 适配器。
 * 负责：
 *   1) 调用后端真实接口
 *   2) 把 wire 类型映射为 UI 类型（src/app/types.ts）
 */
import type {
  Document as UiDocument,
  Session as UiSession,
  Message as UiMessage,
  KGData,
  KGNode,
  KGEdge,
  ToolCall,
} from '../types';
import { apiFetch } from './client';
export { ApiError } from './client';
import {
  DocumentWire,
  DocumentListWire,
  UploadOutWire,
  SessionWire,
  SessionListWire,
  MessageWire,
  MessageListWire,
  KGDocumentWire,
  DocumentPagesWire,
  ChatEvent,
  TaskEvent,
} from './types';
import { openEventSource, postSse } from './sse';

/* -------------------- 适配器：wire → UI -------------------- */

export function toUiDocument(w: DocumentWire): UiDocument {
  return {
    id: w.document_id,
    name: w.original_filename,
    status: w.status,
    progress: w.current_task?.progress_pct,
    error: w.error_message ?? undefined,
    kg: w.kg_stats
      ? { entities: w.kg_stats.entity_count, relations: w.kg_stats.triple_count }
      : undefined,
    uploadedAt: new Date(w.created_at),
  };
}

export function toUiSession(w: SessionWire): UiSession {
  return {
    id: w.session_id,
    documentId: w.document_id,
    name: w.title || `会话 ${w.session_id.slice(0, 4)}`,
    createdAt: new Date(w.created_at),
  };
}

export function toUiMessage(w: MessageWire): UiMessage {
  const tcs: ToolCall[] = (w.tool_calls ?? []).map((t) => ({
    name: t.name,
    status: 'done',
  }));
  return {
    id: w.message_id,
    role: w.role,
    content: w.content,
    toolCalls: tcs.length ? tcs : undefined,
    elapsed: typeof w.latency_ms === 'number' ? w.latency_ms / 1000 : undefined,
    // sources 暂未由后端返回（标记为未开发，UI 不展示）
    sources: undefined,
  };
}

/**
 * 把 langextract 输出的 {entities, triples} 适配为 D3 力导向图所需的
 * {nodes, edges}。
 *
 * object 三种形态：
 *   1. 字符串 "e_xxxxxxxx"（实体 ID）→ 直接生成边
 *   2. 字符串（非实体 ID，字面量）→ 折叠到 subject 的 properties
 *   3. dict {value, unit?, metric_id?}
 *      - 含 metric_id → 生成 subject→metric_id 的边
 *      - 否则 → 折叠到 subject 的 properties
 */
export function toKGData(w: KGDocumentWire): KGData {
  const nodeMap = new Map<string, KGNode>();
  for (const e of w.entities ?? []) {
    nodeMap.set(e.entity_id, {
      id: e.entity_id,
      label: e.label,
      entityClass: e.entity_class || 'Default',
      properties: stringifyProps(e.properties),
      sources: (e.sources ?? []).map((s) => ({
        entityId: e.entity_id,
        documentId: s.document_id,
        location: s.document_id,
        text: '',
        charInterval: s.char_interval ?? null,
        entityLabel: e.label,
        entityClass: e.entity_class || 'Default',
      })),
    });
  }

  const edges: KGEdge[] = [];
  for (const t of w.triples ?? []) {
    const obj = t.object;

    // 1) 解析 object
    let targetId: string | null = null;
    let displayValue: string | null = null;

    if (typeof obj === 'string') {
      // 字符串：判断是否是实体 ID（e_xxxxxxxx 格式）
      if (/^e_[0-9a-f]+$/.test(obj) && nodeMap.has(obj)) {
        targetId = obj;
      } else {
        displayValue = obj;
      }
    } else if (obj && typeof obj === 'object') {
      if ((obj as any).metric_id) {
        targetId = String((obj as any).metric_id);
      }
      const v = (obj as any).value;
      const u = (obj as any).unit;
      if (v != null) displayValue = u ? `${v} ${u}` : String(v);
    }

    // 2) subject 节点：若是 _group_* 等虚拟节点，自动补
    let src = nodeMap.get(t.subject);
    if (!src) {
      src = {
        id: t.subject,
        label: prettyVirtualLabel(t.subject, t.metadata?.group_label),
        entityClass: t.metadata?.extraction_class
          ? capitalize(t.metadata.extraction_class)
          : 'Group',
        properties: t.metadata?.group_label ? { group: t.metadata.group_label } : {},
      };
      nodeMap.set(src.id, src);
    }

    if (targetId && nodeMap.has(targetId)) {
      edges.push({ source: t.subject, target: targetId, predicate: t.predicate });
    } else if (displayValue) {
      // 把字面量挂到 subject 的 properties（去重 / 拼接）
      const key = t.predicate;
      const existing = src.properties[key];
      src.properties[key] = existing && existing !== displayValue
        ? `${existing}; ${displayValue}`
        : displayValue;
    }
  }

  return { nodes: Array.from(nodeMap.values()), edges };
}

function stringifyProps(p: Record<string, unknown> | undefined | null): Record<string, string> {
  const out: Record<string, string> = {};
  if (!p) return out;
  for (const [k, v] of Object.entries(p)) {
    if (v == null) continue;
    out[k] = typeof v === 'string' ? v : JSON.stringify(v);
  }
  return out;
}

function prettyVirtualLabel(id: string, groupLabel?: string): string {
  if (groupLabel) return groupLabel;
  if (id.startsWith('_group_')) return id.slice('_group_'.length);
  return id;
}

function capitalize(s: string): string {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

/* -------------------- documents -------------------- */

export async function listDocuments(): Promise<UiDocument[]> {
  const wire = await apiFetch<DocumentListWire>('/api/documents?page=1&page_size=100&sort=created_at_desc');
  return wire.items.map(toUiDocument);
}

export async function getDocument(documentId: string): Promise<UiDocument> {
  const w = await apiFetch<DocumentWire>(`/api/documents/${documentId}`);
  return toUiDocument(w);
}

export interface UploadResult {
  document: UiDocument;
  taskId: string;
  eventsUrl: string;
}

export async function uploadDocument(file: File): Promise<UploadResult> {
  const fd = new FormData();
  fd.append('file', file, file.name);
  const w = await apiFetch<UploadOutWire>('/api/documents', { method: 'POST', body: fd });
  return {
    document: {
      id: w.document_id,
      name: w.original_filename,
      status: w.status,
      uploadedAt: new Date(w.created_at),
    },
    taskId: w.task_id,
    eventsUrl: w.events_url,
  };
}

export async function deleteDocument(documentId: string): Promise<void> {
  await apiFetch(`/api/documents/${documentId}`, { method: 'DELETE' });
}

export async function getKG(documentId: string): Promise<KGData> {
  const w = await apiFetch<KGDocumentWire>(`/api/documents/${documentId}/kg`);
  return toKGData(w);
}

export async function getDocumentPages(documentId: string): Promise<Record<string, string>> {
  const w = await apiFetch<DocumentPagesWire>(`/api/documents/${documentId}/pages`);
  return w.pages;
}

/* -------------------- tasks (SSE) -------------------- */

export interface TaskProgressHandlers {
  onStageStart?: (stage: string) => void;
  onProgress?: (stage: string, pct: number, detail?: string) => void;
  onStageDone?: (stage: string, elapsedMs: number) => void;
  onComplete?: (kgEntityCount: number | null, kgTripleCount: number | null) => void;
  onError?: (stage: string, message: string) => void;
}

/** 订阅索引进度事件，返回关闭函数。 */
export function subscribeTaskEvents(taskId: string, h: TaskProgressHandlers): () => void {
  return openEventSource<TaskEvent>(`/api/tasks/${taskId}/events`, {
    onEvent: (ev) => {
      switch (ev.event) {
        case 'stage_start':
          h.onStageStart?.(ev.data.stage);
          break;
        case 'progress':
          h.onProgress?.(ev.data.stage, ev.data.pct, ev.data.detail);
          break;
        case 'stage_done':
          h.onStageDone?.(ev.data.stage, ev.data.elapsed_ms);
          break;
        case 'complete':
          h.onComplete?.(
            ev.data.kg_stats?.entity_count ?? null,
            ev.data.kg_stats?.triple_count ?? null
          );
          break;
        case 'error':
          h.onError?.(ev.data.stage, ev.data.message);
          break;
      }
    },
  });
}

/* -------------------- sessions -------------------- */

export async function listSessions(documentId: string): Promise<UiSession[]> {
  const w = await apiFetch<SessionListWire>(
    `/api/sessions?document_id=${encodeURIComponent(documentId)}&page=1&page_size=100`
  );
  // 后端按 updated_at desc 返回，UI 习惯按创建时间升序
  return w.items.map(toUiSession).sort((a, b) => +a.createdAt - +b.createdAt);
}

export async function createSession(documentId: string, title?: string): Promise<UiSession> {
  const w = await apiFetch<SessionWire>('/api/sessions', {
    method: 'POST',
    body: JSON.stringify({ document_id: documentId, title: title ?? null }),
  });
  return toUiSession(w);
}

export async function deleteSession(sessionId: string): Promise<void> {
  await apiFetch(`/api/sessions/${sessionId}`, { method: 'DELETE' });
}

export async function listMessages(sessionId: string): Promise<UiMessage[]> {
  const w = await apiFetch<MessageListWire>(
    `/api/sessions/${sessionId}/messages?page=1&page_size=200`
  );
  return w.items.map(toUiMessage);
}

/* -------------------- chat (SSE) -------------------- */

export interface ChatStreamHandlers {
  onToolCall?: (name: string) => void;
  onToken?: (text: string) => void;
  onComplete?: (info: {
    messageId: string;
    answer: string;
    toolCalls: string[];
    latencyMs: number;
    entityIds: string[];
  }) => void;
  onError?: (message: string) => void;
}

/** 发送问题并以 SSE 接收流式回答。 */
export async function streamChat(
  sessionId: string,
  question: string,
  handlers: ChatStreamHandlers,
  signal?: AbortSignal
): Promise<void> {
  await postSse<ChatEvent>(
    `/api/sessions/${sessionId}/messages`,
    { content: question, stream: true },
    {
      signal,
      onEvent: (ev) => {
        switch (ev.event) {
          case 'tool_call':
            handlers.onToolCall?.(ev.data.name);
            break;
          case 'token':
            handlers.onToken?.(ev.data.text);
            break;
          case 'complete':
            handlers.onComplete?.({
              messageId: ev.data.message_id,
              answer: ev.data.answer,
              toolCalls: ev.data.tool_calls.map((t) => t.name),
              latencyMs: ev.data.latency_ms,
              entityIds: ev.data.entity_ids ?? [],
            });
            break;
          case 'error':
            handlers.onError?.(ev.data.message);
            break;
        }
      },
    }
  );
}

/* -------------------- health -------------------- */

export interface HealthStatus {
  status: 'ok' | 'degraded';
  checks: Record<string, string>;
  uptime_seconds: number;
  version: string;
}

export async function getHealth(): Promise<HealthStatus> {
  return apiFetch<HealthStatus>('/api/health');
}

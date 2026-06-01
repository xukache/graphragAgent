/**
 * 后端 wire 类型（与 backend/app/schemas/*.py 一一对应）。
 * 仅用于 api/ 模块内部，UI 类型仍走 src/app/types.ts。
 */

export type DocStatus =
  | 'pending'
  | 'parsing'
  | 'extracting'
  | 'building_kg'
  | 'ready'
  | 'failed';

export interface KGStatsWire {
  entity_count: number;
  triple_count: number;
  by_class: Record<string, number>;
}

export interface TaskSummaryWire {
  task_id: string;
  state: string;
  progress_pct: number;
}

export interface DocumentWire {
  document_id: string;
  original_filename: string;
  file_size_bytes: number;
  mime_type: string;
  status: DocStatus;
  created_at: number; // ms
  updated_at: number; // ms
  error_message: string | null;
  kg_stats: KGStatsWire | null;
  current_task?: TaskSummaryWire | null;
}

export interface DocumentListWire {
  items: DocumentWire[];
  total: number;
  page: number;
  page_size: number;
}

export interface UploadOutWire {
  document_id: string;
  task_id: string;
  original_filename: string;
  file_size_bytes: number;
  status: DocStatus;
  created_at: number;
  events_url: string;
}

export interface SessionWire {
  session_id: string;
  document_id: string;
  title: string | null;
  created_at: number;
  updated_at: number;
  message_count: number;
}

export interface SessionListWire {
  items: SessionWire[];
  total: number;
  page: number;
  page_size: number;
}

export interface MessageWire {
  message_id: string;
  session_id: string;
  role: 'user' | 'assistant';
  content: string;
  tool_calls?: Array<{ name: string; args?: Record<string, unknown> }> | null;
  tool_call_count?: number;
  latency_ms?: number | null;
  created_at: number;
}

export interface MessageListWire {
  items: MessageWire[];
  total: number;
  page: number;
  page_size: number;
}

/** /api/documents/{id}/pages 返回的按 page_idx 分组的纯文本。 */
export interface DocumentPagesWire {
  pages: Record<string, string>;
}

/** /api/documents/{id}/kg 返回的 KG 文档（与 langextract 输出一致）。 */
export interface KGDocumentWire {
  entities: Array<{
    entity_id: string;
    entity_class: string;
    label: string;
    aliases?: string[];
    properties?: Record<string, unknown>;
    sources?: Array<{
      document_id: string;
      char_interval?: { start_pos: number; end_pos: number };
      alignment_status?: string;
    }>;
  }>;
  triples: Array<{
    subject: string;
    predicate: string;
    object: { value?: string; unit?: string; metric_id?: string } | string;
    metadata?: { document_id?: string; extraction_class?: string; group_label?: string };
  }>;
  stats?: KGStatsWire & { by_predicate?: Record<string, number> };
}

/** SSE 进度事件 payload（来自 /api/tasks/{id}/events）。 */
export type TaskEvent =
  | { event: 'stage_start'; data: { stage: string; message?: string; ts: number } }
  | { event: 'progress'; data: { stage: string; pct: number; detail?: string; ts: number } }
  | { event: 'stage_done'; data: { stage: string; elapsed_ms: number; ts: number } }
  | { event: 'complete'; data: { document_id: string; status: 'ready'; kg_stats: KGStatsWire | null; ts: number } }
  | { event: 'error'; data: { stage: string; message: string; ts: number } };

/** SSE 问答事件 payload（来自 POST /api/sessions/{id}/messages，stream=true）。 */
export type ChatEvent =
  | { event: 'tool_call'; data: { name: string; args?: Record<string, unknown> } }
  | { event: 'token'; data: { text: string } }
  | {
      event: 'complete';
      data: {
        message_id: string;
        answer: string;
        tool_calls: Array<{ name: string; args?: Record<string, unknown> }>;
        tool_call_count: number;
        latency_ms: number;
        entity_ids?: string[];
        ts: number;
      };
    }
  | { event: 'error'; data: { message: string } };

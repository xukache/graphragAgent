export type DocumentStatus = 'pending' | 'parsing' | 'extracting' | 'building_kg' | 'ready' | 'failed';

export interface KGStats {
  entities: number;
  relations: number;
}

export interface Document {
  id: string;
  name: string;
  status: DocumentStatus;
  progress?: number;
  error?: string;
  kg?: KGStats;
  eventsUrl?: string;
  uploadedAt: Date;
}

export interface Session {
  id: string;
  documentId: string;
  name: string;
  createdAt: Date;
}

export type MessageRole = 'user' | 'assistant';

export interface ToolCall {
  name: string;
  status: 'calling' | 'done';
}

export interface Source {
  entityId: string;
  documentId: string;
  location: string;
  text: string;
  charInterval: { start_pos: number; end_pos: number } | null;
  entityLabel: string;
  entityClass: string;
}

/** SourceDrawer 的入参，App.tsx 用它驱动抽屉开关。 */
export interface DrawerSource {
  entityId: string;
  entityLabel: string;
  entityClass: string;
  pageId: string;
  charInterval: { start_pos: number; end_pos: number } | null;
}

export interface Message {
  id: string;
  role: MessageRole;
  content: string;
  toolCalls?: ToolCall[];
  sources?: Source[];
  elapsed?: number;
  isStreaming?: boolean;
  isError?: boolean;
}

export interface KGNode {
  id: string;
  label: string;
  entityClass: string;
  properties: Record<string, string>;
  sources?: Source[];
  x?: number;
  y?: number;
  fx?: number | null;
  fy?: number | null;
}

export interface KGEdge {
  source: string | KGNode;
  target: string | KGNode;
  predicate: string;
}

export interface KGData {
  nodes: KGNode[];
  edges: KGEdge[];
}

/**
 * SSE 工具：
 * - openEventSource: 用浏览器原生 EventSource 订阅 GET 流（/api/tasks/{id}/events）。
 * - postSse: 用 fetch + ReadableStream 解析 POST 触发的 SSE（/api/sessions/{id}/messages）。
 *
 * 后端事件格式：
 *     event: <name>\n
 *     data: <json>\n
 *     \n
 */
import { apiUrl } from './client';

export interface SseHandler<E extends { event: string; data: any }> {
  onEvent: (ev: E) => void;
  onError?: (err: unknown) => void;
  onClose?: () => void;
}

/** GET 风格 SSE：进度事件。 */
export function openEventSource<E extends { event: string; data: any }>(
  path: string,
  handlers: SseHandler<E>
): () => void {
  const es = new EventSource(apiUrl(path));
  const onMsg = (name: string) => (ev: MessageEvent) => {
    let data: any = null;
    try {
      data = JSON.parse(ev.data);
    } catch {
      data = ev.data;
    }
    handlers.onEvent({ event: name, data } as E);
  };
  // 后端 named events
  ['stage_start', 'progress', 'stage_done', 'complete', 'error'].forEach((n) => {
    es.addEventListener(n, onMsg(n));
  });
  es.onerror = (err) => {
    handlers.onError?.(err);
    // EventSource 会自动重连；任务完成后服务端关闭连接，这里只关一次。
  };

  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    es.close();
    handlers.onClose?.();
  };
  // 收到 complete/error 后由调用方主动关闭。
  return close;
}

/** POST 风格 SSE：流式问答。 */
export async function postSse<E extends { event: string; data: any }>(
  path: string,
  body: unknown,
  handlers: SseHandler<E> & { signal?: AbortSignal }
): Promise<void> {
  const res = await fetch(apiUrl(path), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal: handlers.signal,
  });
  if (!res.ok || !res.body) {
    let text = '';
    try { text = await res.text(); } catch { /* noop */ }
    handlers.onError?.(new Error(`SSE failed: ${res.status} ${text || res.statusText}`));
    handlers.onClose?.();
    return;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buf = '';

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });

      // 按 \n\n 切分事件
      let sep: number;
      while ((sep = buf.indexOf('\n\n')) >= 0) {
        const chunk = buf.slice(0, sep);
        buf = buf.slice(sep + 2);
        const ev = parseSseChunk(chunk);
        if (ev) handlers.onEvent(ev as E);
      }
    }
  } catch (err) {
    handlers.onError?.(err);
  } finally {
    handlers.onClose?.();
  }
}

function parseSseChunk(chunk: string): { event: string; data: any } | null {
  const lines = chunk.split('\n');
  let event = 'message';
  const dataLines: string[] = [];
  for (const ln of lines) {
    if (ln.startsWith('event:')) event = ln.slice(6).trim();
    else if (ln.startsWith('data:')) dataLines.push(ln.slice(5).trim());
  }
  if (dataLines.length === 0) return null;
  const raw = dataLines.join('\n');
  let data: any;
  try {
    data = JSON.parse(raw);
  } catch {
    data = raw;
  }
  return { event, data };
}

/**
 * 真实后端 API 客户端。
 *
 * 设计要点：
 * - 所有调用通过 Vite dev proxy `/api` 转发到 FastAPI（localhost:8000）。
 * - 端口/前缀通过 VITE_API_BASE 覆盖，默认 ''（同源 + /api 前缀）。
 * - 任何 4xx/5xx 一律抛 ApiError，包含后端 detail。
 */

const API_BASE: string =
  (import.meta as any).env?.VITE_API_BASE ?? '';

export class ApiError extends Error {
  status: number;
  code: string;
  detail: unknown;
  constructor(status: number, code: string, message: string, detail?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

async function parseError(res: Response): Promise<ApiError> {
  let body: any = null;
  try {
    body = await res.json();
  } catch {
    body = await res.text().catch(() => '');
  }
  const detail = body && typeof body === 'object' ? body.detail ?? body : { message: String(body) };
  const code = (detail && (detail as any).code) || `HTTP_${res.status}`;
  const message = (detail && (detail as any).message) || res.statusText || 'Request failed';
  return new ApiError(res.status, code, message, detail);
}

export async function apiFetch<T = unknown>(
  path: string,
  init: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    ...init,
    headers: {
      Accept: 'application/json',
      ...(init.body && !(init.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
      ...(init.headers ?? {}),
    },
  });
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** 用于打开 SSE 流：直接返回完整 URL（含 base）。 */
export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

const baseUrl = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
export const contentUrl = (id: string) => `${baseUrl}/api/v1/documents/${encodeURIComponent(id)}/content`;
const chatPath = (id: string) => `/chats/${encodeURIComponent(id)}`;

export type ChatStatus = "active" | "archived";
export type Chat = { id: string; title: string; status: ChatStatus };
export type ReusableDocument = { id: string; filename: string; file_type: string };
export type DocumentItem = {
  document_id: string; filename: string; status: string;
  chunk_count: number | null; ingestion_job_id: string | null;
  processing_error: string | null; warnings: string[];
};
export type Job = { status: string; stage: string; completed: number; total: number; attempt: number; max_attempts: number; non_retryable: boolean; error: string | null };
export type Citation = { label: string; filename: string; document_id: string; page: number | null; section: string | null; quote: string; attached: boolean };
export type Message = { id: string; role: string; content: string; status: string; citations: Citation[]; answer_warnings: string[] };
export type Question = {
  question: string;
  scope_mode: "all_ready" | "selected";
  document_ids: string[];
  strategy: "general" | "comparison";
  k: number;
};
export type Receipt = { filename: string; status: string; error: string | null; deduplicated: boolean };
type Page<T> = { items: T[]; total: number };

export class ApiError extends Error {
  constructor(message: string, public code: string, public requestId?: string) {
    super(message);
  }
}

export function errorText(error: unknown) {
  if (error instanceof ApiError && error.requestId) {
    return `${error.message} (Request ID: ${error.requestId})`;
  }
  return error instanceof Error ? error.message : "An unexpected error occurred.";
}

async function request<T>(path: string, init: RequestInit = {}, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  if (signal?.aborted) abort();
  const timeout = setTimeout(abort, 180_000);
  const headers = new Headers(init.headers);
  const clientId = globalThis.crypto?.randomUUID?.();
  if (clientId) headers.set("X-Client-Request-ID", clientId.replaceAll("-", ""));
  try {
    let response: Response;
    try {
      response = await fetch(`${baseUrl}/api/v1${path}`, { ...init, headers, signal: controller.signal, cache: "no-store" });
    } catch (error) {
      if (signal?.aborted) throw error;
      throw new ApiError(init.method
        ? "The request outcome is unknown. Refresh before trying again."
        : "Cannot reach FastAPI. Check that it is running and allows this frontend origin.", "connection_failed");
    }
    const payload = await response.json().catch(() => null);
    const requestId = payload?.request_id || response.headers.get("X-Request-ID") || undefined;
    if (!response.ok) {
      throw new ApiError(payload?.error?.message || `API returned HTTP ${response.status}.`,
        payload?.error?.code || "api_error", requestId);
    }
    if (payload === null) throw new ApiError("The API returned an unreadable response.", "invalid_response", requestId);
    return payload as T;
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", abort);
  }
}

async function items<T>(path: string, signal?: AbortSignal, filters: Record<string, string> = {}) {
  const result: T[] = [];
  for (let offset = 0; offset <= 10000;) {
    const params = new URLSearchParams({ ...filters, limit: "100", offset: String(offset) });
    const page = await request<Page<T>>(`${path}?${params}`, {}, signal);
    result.push(...page.items);
    offset += page.items.length;
    if (offset >= page.total || !page.items.length) return result;
  }
  throw new ApiError("The API pagination limit was reached.", "pagination_limit");
}

export const api = {
  chats: (signal?: AbortSignal, status: ChatStatus = "active") => items<Chat>("/chats", signal, { status }),
  chat: (id: string, signal?: AbortSignal) => request<Chat>(chatPath(id), {}, signal),
  renameChat: (id: string, title: string) => request<Chat>(chatPath(id), {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }),
  }),
  setArchived: (id: string, archived: boolean) => request<Chat>(
    `${chatPath(id)}/${archived ? "archive" : "restore"}`, { method: "POST" },
  ),
  reusableDocuments: (signal?: AbortSignal) => items<ReusableDocument>("/documents/reusable", signal),
  attach: (id: string, documentId: string) => request<{changed: boolean}>(`${chatPath(id)}/attachments`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ document_id: documentId, ready_only: true }),
  }),
  createChat: (title: string) => request<Chat>("/chats", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }),
  }),
  documents: (id: string, signal?: AbortSignal) => items<DocumentItem>(`${chatPath(id)}/documents`, signal),
  messages: (id: string, signal?: AbortSignal) => items<Message>(`${chatPath(id)}/messages`, signal),
  ask: (id: string, question: Question) => request<{ turn_id: string }>(`${chatPath(id)}/messages`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(question),
  }),
  upload: (id: string, files: File[]) => {
    const body = new FormData();
    files.forEach(file => body.append("files", file));
    return request<{items: Receipt[]; accepted: number; rejected: number}>(`${chatPath(id)}/documents`, { method: "POST", body });
  },
  job: (id: string, signal?: AbortSignal) => request<Job>(`/ingestion-jobs/${encodeURIComponent(id)}`, {}, signal),
  retry: (id: string) => request<Job>(`/ingestion-jobs/${encodeURIComponent(id)}/retry`, { method: "POST" }),
  detach: (chat: string, doc: string) => request(`${chatPath(chat)}/documents/${encodeURIComponent(doc)}`, { method: "DELETE" }),
};

/**
 * Typed API client for the Private RAG Accelerator backend (T044).
 *
 * Types are generated from `specs/001-private-rag-accelerator/contracts/api-openapi.yaml`
 * via `npm run gen:api` (openapi-typescript). The generated file is
 * `src/lib/types/api.ts` and IS committed; regenerate after any contract
 * change.
 *
 * Bearer tokens are attached automatically:
 *   - Server side: read the access_token from the Auth.js JWT session.
 *   - Client side: callers must pass a token explicitly (server components
 *     or Route Handlers should resolve the token and forward it).
 */
import type { components, paths } from './types/api';

// --- Generated schema aliases -----------------------------------------------

export type Conversation = components['schemas']['Conversation'];
export type ConversationSummary = components['schemas']['ConversationSummary'];
export type Turn = components['schemas']['Turn'];
export type Citation = components['schemas']['Citation'];
export type DocumentMeta = components['schemas']['DocumentMeta'];
export type ChatRequest = components['schemas']['ChatRequest'];
export type AdminStats = components['schemas']['AdminStats'];
export type ApiErrorBody = components['schemas']['Error'];

export type MeResponse = paths['/me']['get']['responses']['200']['content']['application/json'];
export type ConversationsListResponse =
  paths['/conversations']['get']['responses']['200']['content']['application/json'];

// --- Errors -----------------------------------------------------------------

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId?: string;
  readonly details?: Record<string, unknown>;
  constructor(
    status: number,
    body: Partial<ApiErrorBody> & { requestId?: string },
    fallbackMessage?: string
  ) {
    super(body.message ?? fallbackMessage ?? `HTTP ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.code = body.code ?? `http_${status}`;
    this.requestId = body.requestId;
    this.details = body.details as Record<string, unknown> | undefined;
  }
}

// --- Client construction ----------------------------------------------------

export interface ApiClientOptions {
  /** Base URL for the API. Server-only callers should pass `API_BASE_URL`. */
  baseUrl?: string;
  /** Bearer token to attach. Resolved per-request when supplied as a function. */
  token?: string | (() => Promise<string | undefined> | string | undefined);
  /** Override `fetch` (e.g. for tests). */
  fetch?: typeof fetch;
}

function resolveBaseUrl(opts?: ApiClientOptions): string {
  if (opts?.baseUrl) return opts.baseUrl;
  // Server-side: prefer the internal-VNet base URL.
  if (typeof window === 'undefined') {
    return process.env.API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? '';
  }
  // Client-side: must be a public env var.
  return process.env.NEXT_PUBLIC_API_BASE_URL ?? '';
}

async function resolveToken(opts?: ApiClientOptions): Promise<string | undefined> {
  if (!opts?.token) return undefined;
  return typeof opts.token === 'function' ? await opts.token() : opts.token;
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'DELETE' | 'PUT' | 'PATCH';
  query?: Record<string, string | number | undefined>;
  body?: unknown;
  formData?: FormData;
  signal?: AbortSignal;
  /** Override `Accept` header (used for binary responses). */
  accept?: string;
}

async function request<T>(
  client: ApiClientOptions | undefined,
  path: string,
  options: RequestOptions = {}
): Promise<T> {
  const baseUrl = resolveBaseUrl(client);
  if (!baseUrl) {
    throw new Error(
      'API base URL not configured. Set API_BASE_URL (server) or NEXT_PUBLIC_API_BASE_URL (client).'
    );
  }
  const url = new URL(path.startsWith('/') ? path.slice(1) : path, ensureTrailingSlash(baseUrl));
  if (options.query) {
    for (const [k, v] of Object.entries(options.query)) {
      if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
    }
  }

  const token = await resolveToken(client);
  const headers: Record<string, string> = {
    Accept: options.accept ?? 'application/json',
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  let body: BodyInit | undefined;
  if (options.formData) {
    body = options.formData;
    // Browser sets multipart boundary; do not force Content-Type.
  } else if (options.body !== undefined) {
    body = JSON.stringify(options.body);
    headers['Content-Type'] = 'application/json';
  }

  const fetchImpl = client?.fetch ?? fetch;
  const res = await fetchImpl(url.toString(), {
    method: options.method ?? 'GET',
    headers,
    body,
    signal: options.signal,
    cache: 'no-store',
  });

  if (!res.ok) {
    const requestId = res.headers.get('x-request-id') ?? undefined;
    let parsed: Partial<ApiErrorBody> = {};
    try {
      parsed = (await res.json()) as Partial<ApiErrorBody>;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, { ...parsed, requestId });
  }

  if (res.status === 204) return undefined as T;
  if ((options.accept ?? '').includes('application/json') === false && options.accept) {
    return (await res.blob()) as unknown as T;
  }
  const ctype = res.headers.get('content-type') ?? '';
  if (ctype.includes('application/json')) return (await res.json()) as T;
  return (await res.text()) as unknown as T;
}

function ensureTrailingSlash(u: string): string {
  return u.endsWith('/') ? u : `${u}/`;
}

// --- Public API -------------------------------------------------------------

export interface ApiClient {
  me(signal?: AbortSignal): Promise<MeResponse>;
  listConversations(
    params?: { limit?: number; continuationToken?: string },
    signal?: AbortSignal
  ): Promise<ConversationsListResponse>;
  createConversation(signal?: AbortSignal): Promise<Conversation>;
  getConversation(id: string, signal?: AbortSignal): Promise<Conversation>;
  deleteConversation(id: string, signal?: AbortSignal): Promise<void>;
  uploadDocument(
    file: File | Blob,
    conversationId: string,
    signal?: AbortSignal,
    fileName?: string
  ): Promise<DocumentMeta>;
  /** One-shot chat call returning the final SSE-aggregated response (or undefined for stream-only callers). */
  chat(req: ChatRequest, signal?: AbortSignal): Promise<Response>;
  /** Async-generator over SSE chat events. */
  chatStream(req: ChatRequest, signal?: AbortSignal): AsyncGenerator<ChatStreamEvent, void, void>;
  getCitationDocument(documentId: string, page?: number, signal?: AbortSignal): Promise<Blob>;
  adminStats(signal?: AbortSignal): Promise<AdminStats>;
  adminListRuns(
    params?: { scope?: 'shared' | 'user'; limit?: number },
    signal?: AbortSignal
  ): Promise<unknown>;
  adminReindex(signal?: AbortSignal): Promise<void>;
}

export type ChatStreamEvent =
  | { type: 'delta'; data: { text: string } }
  | { type: 'citations'; data: { citations: Citation[] } }
  | { type: 'done'; data: Record<string, unknown> }
  | { type: 'error'; data: { code?: string; message: string } }
  | { type: string; data: unknown };

export function createApiClient(options?: ApiClientOptions): ApiClient {
  const opts = options;

  return {
    me: (signal) => request<MeResponse>(opts, '/me', { signal }),

    listConversations: (params, signal) =>
      request<ConversationsListResponse>(opts, '/conversations', {
        query: params,
        signal,
      }),

    createConversation: (signal) =>
      request<Conversation>(opts, '/conversations', { method: 'POST', signal }),

    getConversation: (id, signal) =>
      request<Conversation>(opts, `/conversations/${encodeURIComponent(id)}`, { signal }),

    deleteConversation: (id, signal) =>
      request<void>(opts, `/conversations/${encodeURIComponent(id)}`, {
        method: 'DELETE',
        signal,
      }),

    uploadDocument: (file, conversationId, signal, fileName) => {
      const fd = new FormData();
      fd.append('conversationId', conversationId);
      fd.append('file', file, fileName);
      return request<DocumentMeta>(opts, '/uploads', {
        method: 'POST',
        formData: fd,
        signal,
      });
    },

    chat: async (req, signal) => {
      const baseUrl = resolveBaseUrl(opts);
      if (!baseUrl) throw new Error('API base URL not configured.');
      const token = await resolveToken(opts);
      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
      };
      if (token) headers['Authorization'] = `Bearer ${token}`;
      const fetchImpl = opts?.fetch ?? fetch;
      const res = await fetchImpl(new URL('chat', ensureTrailingSlash(baseUrl)).toString(), {
        method: 'POST',
        headers,
        body: JSON.stringify(req),
        signal,
      });
      if (!res.ok) {
        let parsed: Partial<ApiErrorBody> = {};
        try {
          parsed = (await res.json()) as Partial<ApiErrorBody>;
        } catch {
          /* ignore */
        }
        throw new ApiError(res.status, parsed);
      }
      return res;
    },

    async *chatStream(req, signal) {
      const res = await this.chat(req, signal);
      if (!res.body) return;
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        // SSE events are separated by a blank line.
        let idx;
        while ((idx = buf.indexOf('\n\n')) !== -1) {
          const raw = buf.slice(0, idx);
          buf = buf.slice(idx + 2);
          const event = parseSseEvent(raw);
          if (event) yield event;
        }
      }
    },

    getCitationDocument: (documentId, page, signal) =>
      request<Blob>(opts, `/citations/${encodeURIComponent(documentId)}`, {
        query: page ? { page } : undefined,
        accept: 'application/octet-stream',
        signal,
      }),

    adminStats: (signal) => request<AdminStats>(opts, '/admin/stats', { signal }),

    adminListRuns: (params, signal) =>
      request<unknown>(opts, '/admin/runs', { query: params, signal }),

    adminReindex: (signal) => request<void>(opts, '/admin/reindex', { method: 'POST', signal }),
  };
}

function parseSseEvent(raw: string): ChatStreamEvent | null {
  let event = 'message';
  const dataLines: string[] = [];
  for (const line of raw.split('\n')) {
    if (!line || line.startsWith(':')) continue;
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart());
  }
  if (dataLines.length === 0) return null;
  const dataStr = dataLines.join('\n');
  try {
    return { type: event, data: JSON.parse(dataStr) } as ChatStreamEvent;
  } catch {
    return { type: event, data: dataStr } as ChatStreamEvent;
  }
}

/**
 * Convenience: build an API client bound to the current Auth.js session.
 * Server-component / route-handler use only — relies on `auth()` which
 * imports Node-only modules.
 */
export async function getServerApiClient(): Promise<ApiClient> {
  const { auth } = await import('./auth');
  return createApiClient({
    token: async () => {
      const session = await auth();
      return session?.accessToken;
    },
  });
}

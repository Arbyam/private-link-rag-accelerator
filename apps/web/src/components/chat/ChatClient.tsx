'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { ChatPane } from './ChatPane';
import type { ChatMessage, Citation } from './types';
import { readSseStream } from '@/lib/sse';
import { useAnnouncer } from '@/components/shell/LiveRegion';

/**
 * Client-side chat shell (T087).
 *
 * Wires our custom `POST /chat` SSE stream (events: `delta`, `citations`,
 * `done`, `error`) into the {@link ChatPane} render contract. We use a
 * hand-rolled fetch + SSE consumer instead of `@ai-sdk/react`'s `useChat`
 * because our event names + payloads do not match either of the AI SDK 4
 * built-in stream protocols (`text` / `data`).
 *
 * Auth: the server component that renders us resolves the user's Auth.js
 * access token and passes it as `accessToken`. We forward it as
 * `Authorization: Bearer <token>` on every request.
 */

export interface ChatClientProps {
  initialConversationId: string | null;
  initialMessages?: ChatMessage[];
  accessToken: string;
  apiBaseUrl: string;
}

interface SendError {
  message: string;
}

export function ChatClient({
  initialConversationId,
  initialMessages = [],
  accessToken,
  apiBaseUrl,
}: ChatClientProps) {
  const router = useRouter();
  const { announce } = useAnnouncer();
  const [messages, setMessages] = React.useState<ChatMessage[]>(initialMessages);
  const [isStreaming, setIsStreaming] = React.useState(false);
  const [error, setError] = React.useState<SendError | null>(null);
  const conversationIdRef = React.useRef<string | null>(initialConversationId);
  const abortRef = React.useRef<AbortController | null>(null);

  const baseUrl = ensureTrailingSlash(apiBaseUrl);

  const updateTrailingAssistant = React.useCallback(
    (mutator: (m: ChatMessage) => ChatMessage) => {
      setMessages((prev) => {
        if (prev.length === 0) return prev;
        const last = prev[prev.length - 1];
        if (last.role !== 'assistant') return prev;
        return [...prev.slice(0, -1), mutator(last)];
      });
    },
    []
  );

  const handleStop = React.useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const handleSend = React.useCallback(
    async (text: string) => {
      if (isStreaming) return;
      setError(null);

      const userMessage: ChatMessage = {
        id: cryptoRandomId(),
        role: 'user',
        content: text,
      };
      const assistantPlaceholder: ChatMessage = {
        id: cryptoRandomId(),
        role: 'assistant',
        content: '',
        isStreaming: true,
      };
      setMessages((prev) => [...prev, userMessage, assistantPlaceholder]);
      setIsStreaming(true);
      announce('Assistant is responding…', 'polite');

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        // Ensure we have a conversationId. ChatRequest requires one.
        let conversationId = conversationIdRef.current;
        const isNewConversation = conversationId === null;
        if (!conversationId) {
          conversationId = await createConversation(baseUrl, accessToken, controller.signal);
          conversationIdRef.current = conversationId;
        }

        const res = await fetch(new URL('chat', baseUrl).toString(), {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Accept: 'text/event-stream',
            Authorization: `Bearer ${accessToken}`,
          },
          body: JSON.stringify({
            conversationId,
            message: text,
          }),
          signal: controller.signal,
        });

        if (!res.ok) {
          const body = await safeReadJson(res);
          throw new Error(body?.message ?? `Chat request failed (${res.status})`);
        }

        for await (const ev of readSseStream(res, controller.signal)) {
          if (ev.event === 'delta') {
            const payload = safeJsonParse<{ text?: string }>(ev.data);
            const token = payload?.text ?? '';
            if (token) {
              updateTrailingAssistant((m) => ({ ...m, content: m.content + token }));
            }
          } else if (ev.event === 'citations') {
            const payload = safeJsonParse<{ citations?: Citation[] }>(ev.data);
            if (payload?.citations) {
              const cits = payload.citations;
              updateTrailingAssistant((m) => ({ ...m, citations: cits }));
            }
          } else if (ev.event === 'done') {
            const payload = safeJsonParse<{ conversationId?: string }>(ev.data);
            if (payload?.conversationId) {
              conversationIdRef.current = payload.conversationId;
            }
            updateTrailingAssistant((m) => ({ ...m, isStreaming: false }));
            announce('Assistant response complete.', 'polite');
            if (isNewConversation && conversationIdRef.current) {
              // Replace URL so refresh / back-button hydrates from /conversations/{id}.
              router.replace(`/chat/${conversationIdRef.current}`);
            }
          } else if (ev.event === 'error') {
            const payload = safeJsonParse<{ message?: string; code?: string }>(ev.data);
            throw new Error(payload?.message ?? 'Chat stream error');
          }
        }

        // Defensive: server closed without a `done` event — clear streaming flag.
        updateTrailingAssistant((m) => (m.isStreaming ? { ...m, isStreaming: false } : m));
      } catch (err) {
        const message =
          err instanceof DOMException && err.name === 'AbortError'
            ? 'Generation stopped.'
            : err instanceof Error
              ? err.message
              : 'Something went wrong.';
        setError({ message });
        announce(message, 'assertive');
        updateTrailingAssistant((m) => ({
          ...m,
          isStreaming: false,
          content: m.content || `_${message}_`,
        }));
      } finally {
        setIsStreaming(false);
        abortRef.current = null;
      }
    },
    [accessToken, announce, baseUrl, isStreaming, router, updateTrailingAssistant]
  );

  const handleCitationActivate = React.useCallback(
    (citation: Citation) => {
      const params = new URLSearchParams();
      if (citation.page) params.set('page', String(citation.page));
      const qs = params.toString();
      router.push(`/citations/${encodeURIComponent(citation.documentId)}${qs ? `?${qs}` : ''}`);
    },
    [router]
  );

  return (
    <div className="flex h-full flex-col">
      {error ? (
        <div
          role="alert"
          className="border-b border-[var(--border)] bg-[var(--destructive)]/10 px-6 py-2 text-sm text-[var(--destructive)]"
        >
          {error.message}
        </div>
      ) : null}
      <div className="flex-1 min-h-0">
        <ChatPane
          messages={messages}
          isStreaming={isStreaming}
          onSend={handleSend}
          onStop={handleStop}
          onCitationActivate={handleCitationActivate}
        />
      </div>
    </div>
  );
}

// --- helpers ---------------------------------------------------------------

function ensureTrailingSlash(u: string): string {
  return u.endsWith('/') ? u : `${u}/`;
}

async function createConversation(
  baseUrl: string,
  accessToken: string,
  signal: AbortSignal
): Promise<string> {
  const res = await fetch(new URL('conversations', baseUrl).toString(), {
    method: 'POST',
    headers: {
      Accept: 'application/json',
      Authorization: `Bearer ${accessToken}`,
    },
    signal,
  });
  if (!res.ok) {
    const body = await safeReadJson(res);
    throw new Error(body?.message ?? `Failed to create conversation (${res.status})`);
  }
  const json = (await res.json()) as { id?: string };
  if (!json.id) throw new Error('Server returned conversation without an id.');
  return json.id;
}

async function safeReadJson(res: Response): Promise<{ message?: string } | null> {
  try {
    return (await res.json()) as { message?: string };
  } catch {
    return null;
  }
}

function safeJsonParse<T>(s: string): T | null {
  try {
    return JSON.parse(s) as T;
  } catch {
    return null;
  }
}

function cryptoRandomId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

/**
 * Tiny SSE (Server-Sent Events) parser. Consumes a streaming `Response.body`
 * and yields `{ event, data }` objects, where `data` is the event's `data:`
 * payload as a string (the caller decides how to parse it — typically JSON).
 *
 * Implements just enough of the SSE wire format
 * (https://html.spec.whatwg.org/multipage/server-sent-events.html) to handle
 * the chat router's `delta` / `citations` / `done` / `error` events:
 *   - Multiple `data:` lines per event are joined with `\n`.
 *   - `event:` sets the event name (defaults to `"message"`).
 *   - Comment lines (starting with `:`) and unknown fields are ignored.
 *   - Events are terminated by a blank line (`\n\n`).
 */

export interface SseEvent {
  event: string;
  data: string;
}

/**
 * Parse a single raw SSE event block (already split on the blank-line
 * separator) into `{ event, data }`. Returns `null` for empty / comment-only
 * blocks.
 */
export function parseSseEventBlock(raw: string): SseEvent | null {
  let event = 'message';
  const dataLines: string[] = [];
  for (const line of raw.split('\n')) {
    if (!line) continue;
    if (line.startsWith(':')) continue;
    if (line.startsWith('event:')) {
      event = line.slice(6).trim();
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).replace(/^ /, ''));
    }
    // id: / retry: / unknown fields are intentionally ignored.
  }
  if (dataLines.length === 0) return null;
  return { event, data: dataLines.join('\n') };
}

/**
 * Async-iterate SSE events from a fetch `Response`. Throws if the response
 * has no body. Stops cleanly when the server closes the stream.
 */
export async function* readSseStream(
  response: Response,
  signal?: AbortSignal
): AsyncGenerator<SseEvent, void, void> {
  if (!response.body) {
    throw new Error('SSE response has no body');
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';

  const onAbort = () => reader.cancel().catch(() => {});
  signal?.addEventListener('abort', onAbort, { once: true });

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let idx: number;
      // Events are separated by a blank line — handle both `\n\n` and `\r\n\r\n`.
      while ((idx = nextEventBoundary(buf)) !== -1) {
        const raw = buf.slice(0, idx).replace(/\r\n/g, '\n');
        // Advance past the boundary (2 chars for \n\n, 4 for \r\n\r\n).
        const boundaryLen = buf.startsWith('\r\n\r\n', idx) ? 4 : 2;
        buf = buf.slice(idx + boundaryLen);
        const ev = parseSseEventBlock(raw);
        if (ev) yield ev;
      }
    }
    // Flush any trailing event (servers usually terminate with \n\n, but be lenient).
    const rest = buf.trim();
    if (rest) {
      const ev = parseSseEventBlock(rest.replace(/\r\n/g, '\n'));
      if (ev) yield ev;
    }
  } finally {
    signal?.removeEventListener('abort', onAbort);
    try {
      reader.releaseLock();
    } catch {
      /* noop */
    }
  }
}

function nextEventBoundary(buf: string): number {
  const a = buf.indexOf('\n\n');
  const b = buf.indexOf('\r\n\r\n');
  if (a === -1) return b;
  if (b === -1) return a;
  return Math.min(a, b);
}

'use client';

import * as React from 'react';
import { Send, Square } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { ScrollArea } from '@/components/ui/scroll-area';
import { MessageBubble } from './MessageBubble';
import { cn } from '@/lib/utils';
import type { ChatMessage, Citation } from './types';

export type ChatPaneProps = {
  messages: ChatMessage[];
  isStreaming: boolean;
  onSend: (text: string) => void;
  onStop?: () => void;
  onCitationActivate?: (citation: Citation) => void;
  title?: string;
  placeholder?: string;
  emptyStateSuggestions?: string[];
  className?: string;
};

const DEFAULT_SUGGESTIONS = [
  'What documents do I have access to?',
  'Summarize the latest policy updates.',
  'Compare the key risks across my uploaded reports.',
];

export function ChatPane({
  messages,
  isStreaming,
  onSend,
  onStop,
  onCitationActivate,
  title,
  placeholder = 'Ask a question about your documents…',
  emptyStateSuggestions = DEFAULT_SUGGESTIONS,
  className,
}: ChatPaneProps) {
  const [draft, setDraft] = React.useState('');
  const textareaRef = React.useRef<HTMLTextAreaElement>(null);
  const scrollRef = React.useRef<HTMLDivElement>(null);

  React.useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
  }, [draft]);

  React.useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [messages, isStreaming]);

  const submit = React.useCallback(() => {
    const text = draft.trim();
    if (!text || isStreaming) return;
    onSend(text);
    setDraft('');
    // Keep focus in the textarea so a follow-up question is one keystroke away.
    requestAnimationFrame(() => textareaRef.current?.focus());
  }, [draft, isStreaming, onSend]);

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  };

  const isEmpty = messages.length === 0;

  return (
    <section
      className={cn(
        'flex h-full flex-col bg-[var(--background)] text-[var(--foreground)]',
        className
      )}
      aria-label="Chat conversation"
    >
      {title ? (
        <header className="border-b border-[var(--border)] px-6 py-4">
          <h2 className="truncate text-base font-semibold">{title}</h2>
        </header>
      ) : null}

      <div className="flex-1 min-h-0">
        <ScrollArea className="h-full">
          <div ref={scrollRef} className="mx-auto max-w-3xl px-6 py-8">
            {isEmpty ? (
              <EmptyState
                suggestions={emptyStateSuggestions}
                onPick={(s) => {
                  setDraft(s);
                  textareaRef.current?.focus();
                }}
              />
            ) : (
              <ol className="flex flex-col gap-4" aria-label="Messages">
                {messages.map((m) => (
                  <li key={m.id}>
                    <MessageBubble
                      role={m.role}
                      content={m.content}
                      citations={m.citations}
                      isStreaming={m.isStreaming}
                      onCitationActivate={onCitationActivate}
                    />
                  </li>
                ))}
              </ol>
            )}
          </div>
        </ScrollArea>
      </div>

      <footer className="border-t border-[var(--border)] bg-[var(--background)] px-6 py-4">
        <div className="mx-auto flex max-w-3xl items-end gap-2">
          <Textarea
            ref={textareaRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            rows={1}
            aria-label="Message input"
            disabled={isStreaming && !onStop}
          />
          {isStreaming && onStop ? (
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={onStop}
              aria-label="Stop generating"
            >
              <Square className="h-4 w-4" aria-hidden="true" />
            </Button>
          ) : (
            <Button
              type="button"
              size="icon"
              onClick={submit}
              disabled={!draft.trim() || isStreaming}
              aria-disabled={!draft.trim() || isStreaming}
              aria-label="Send message"
            >
              <Send className="h-4 w-4" aria-hidden="true" />
            </Button>
          )}
        </div>
        <p className="mx-auto mt-2 max-w-3xl text-center text-[11px] text-[var(--muted-foreground)]">
          Press Enter to send · Shift + Enter for newline
        </p>
      </footer>
    </section>
  );
}

function EmptyState({
  suggestions,
  onPick,
}: {
  suggestions: string[];
  onPick: (s: string) => void;
}) {
  return (
    <div className="flex flex-col items-center gap-6 py-16 text-center">
      <div>
        <h3 className="text-xl font-semibold">Ask your documents anything</h3>
        <p className="mt-2 text-sm text-[var(--muted-foreground)]">
          Answers are grounded in your private corpus and cite their sources.
        </p>
      </div>
      <ul className="grid w-full max-w-xl gap-2 text-left">
        {suggestions.map((s) => (
          <li key={s}>
            <button
              type="button"
              onClick={() => onPick(s)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--muted)] px-4 py-3 text-sm text-[var(--foreground)] transition-colors hover:border-[var(--accent)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
            >
              {s}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

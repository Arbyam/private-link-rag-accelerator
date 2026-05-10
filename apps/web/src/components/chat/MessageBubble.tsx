'use client';

import * as React from 'react';
import { CitationChip } from './CitationChip';
import { cn } from '@/lib/utils';
import type { Citation } from './types';

export type MessageBubbleProps = {
  role: 'user' | 'assistant' | 'system';
  content: string;
  citations?: Citation[];
  isStreaming?: boolean;
  onCitationActivate?: (citation: Citation) => void;
  className?: string;
};

const CITATION_PATTERN = /\[(\d+)\]/g;

function renderContentWithCitations(
  content: string,
  citations: Citation[] | undefined,
  onActivate: ((citation: Citation) => void) | undefined
): { body: React.ReactNode; usedIndices: Set<number> } {
  const used = new Set<number>();
  if (!citations || citations.length === 0) {
    return { body: <PlainText text={content} />, usedIndices: used };
  }

  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let key = 0;
  for (const match of content.matchAll(CITATION_PATTERN)) {
    const idx = Number(match[1]);
    const start = match.index ?? 0;
    if (start > lastIndex) {
      parts.push(<PlainText key={`t-${key++}`} text={content.slice(lastIndex, start)} />);
    }
    const citation = citations[idx - 1];
    if (citation) {
      used.add(idx);
      parts.push(
        <CitationChip
          key={`c-${key++}-${idx}`}
          citation={citation}
          index={idx}
          onActivate={onActivate}
          className="mx-0.5 align-baseline"
        />
      );
    } else {
      parts.push(<span key={`u-${key++}`}>{match[0]}</span>);
    }
    lastIndex = start + match[0].length;
  }
  if (lastIndex < content.length) {
    parts.push(<PlainText key={`t-${key++}`} text={content.slice(lastIndex)} />);
  }
  return { body: <>{parts}</>, usedIndices: used };
}

function PlainText({ text }: { text: string }) {
  return <span className="whitespace-pre-wrap">{text}</span>;
}

export function MessageBubble({
  role,
  content,
  citations,
  isStreaming,
  onCitationActivate,
  className,
}: MessageBubbleProps) {
  const isUser = role === 'user';
  const isSystem = role === 'system';

  const { body, usedIndices } = React.useMemo(
    () => renderContentWithCitations(content, citations, onCitationActivate),
    [content, citations, onCitationActivate]
  );

  const trailingCitations = citations?.filter((_, i) => !usedIndices.has(i + 1)) ?? [];

  return (
    <div
      className={cn('flex w-full', isUser ? 'justify-end' : 'justify-start', className)}
      data-role={role}
    >
      <article
        aria-label={
          isUser
            ? 'Your message'
            : isSystem
              ? 'System message'
              : isStreaming
                ? 'Assistant response, streaming'
                : 'Assistant response'
        }
        className={cn(
          'max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed',
          isUser && 'bg-[var(--accent)] text-[var(--accent-foreground)] rounded-br-sm',
          !isUser && !isSystem && 'bg-[var(--muted)] text-[var(--foreground)] rounded-bl-sm',
          isSystem &&
            'border border-dashed border-[var(--border)] bg-transparent text-[var(--muted-foreground)] italic'
        )}
      >
        <div>
          {body}
          {isStreaming ? (
            <span
              aria-hidden="true"
              className="ml-1 inline-block h-2 w-2 animate-pulse motion-reduce:animate-none rounded-full bg-current align-middle"
            />
          ) : null}
        </div>
        {trailingCitations.length > 0 ? (
          <div className="mt-2 flex flex-wrap gap-1">
            {trailingCitations.map((c, i) => {
              const originalIndex = (citations ?? []).indexOf(c) + 1;
              return (
                <CitationChip
                  key={`tc-${i}`}
                  citation={c}
                  index={originalIndex}
                  onActivate={onCitationActivate}
                />
              );
            })}
          </div>
        ) : null}
      </article>
    </div>
  );
}

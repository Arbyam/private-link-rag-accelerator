'use client';

import * as React from 'react';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';
import type { Citation } from './types';

export type CitationChipProps = {
  citation: Citation;
  /** 1-based index matching the LLM's `[N]` brackets in the message body. */
  index: number;
  onActivate?: (citation: Citation) => void;
  className?: string;
};

function getDocumentLabel(c: Citation): string {
  return c.documentId;
}

export function CitationChip({ citation, index, onActivate, className }: CitationChipProps) {
  const handleActivate = React.useCallback(() => {
    onActivate?.(citation);
  }, [citation, onActivate]);

  const handleKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      handleActivate();
    }
  };

  const label = getDocumentLabel(citation);
  const ariaLabel = `Citation ${index}: ${label}, page ${citation.page}`;

  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={handleActivate}
            onKeyDown={handleKeyDown}
            aria-label={ariaLabel}
            className={cn(
              'inline-flex max-w-[14rem] items-center gap-1 rounded-full border border-[var(--border)] bg-[var(--muted)] px-2 py-0.5 text-xs font-medium text-[var(--foreground)] transition-colors hover:bg-[var(--accent)] hover:text-[var(--accent-foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]',
              className
            )}
          >
            <span className="font-semibold tabular-nums">[{index}]</span>
            <span className="truncate text-[var(--muted-foreground)] group-hover:text-inherit">
              {label}
              {citation.page ? ` · p.${citation.page}` : ''}
            </span>
          </button>
        </TooltipTrigger>
        {citation.snippet ? (
          <TooltipContent side="top" align="start">
            <p className="whitespace-pre-wrap">{citation.snippet}</p>
          </TooltipContent>
        ) : null}
      </Tooltip>
    </TooltipProvider>
  );
}

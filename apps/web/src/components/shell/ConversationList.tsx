'use client';

/**
 * Left-rail list of the caller's conversations (T090).
 *
 * Client component because it needs `usePathname()` for active-route
 * highlighting and will host future per-row actions (rename/delete).
 */
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import type { ConversationSummary } from '@/lib/api';
import { relativeTime } from '@/lib/format';
import { cn } from '@/lib/utils';

export interface ConversationListProps {
  conversations: ConversationSummary[];
}

export function ConversationList({ conversations }: ConversationListProps) {
  const pathname = usePathname();

  if (conversations.length === 0) {
    return (
      <nav
        role="navigation"
        aria-label="Conversations"
        className="flex h-full flex-col items-start gap-2 px-3 py-4 text-sm text-[var(--muted-foreground)]"
      >
        <p>No conversations yet.</p>
        <Link
          href="/chat"
          className="rounded-sm font-medium text-[var(--accent)] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
        >
          Start one →
        </Link>
      </nav>
    );
  }

  return (
    <nav
      role="navigation"
      aria-label="Conversations"
      className="flex flex-col gap-0.5 px-2 py-2"
    >
      <ul className="flex flex-col gap-0.5">
        {conversations.map((c) => {
          const href = `/chat/${c.id}`;
          const isActive = pathname === href || pathname?.startsWith(`${href}/`);
          return (
            <li key={c.id}>
              <Link
                href={href}
                aria-current={isActive ? 'page' : undefined}
                className={cn(
                  'group block rounded-md px-3 py-2 text-sm transition-colors',
                  'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]',
                  isActive
                    ? 'bg-[var(--muted)] text-[var(--foreground)]'
                    : 'text-[var(--muted-foreground)] hover:bg-[var(--muted)] hover:text-[var(--foreground)]'
                )}
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="truncate font-medium">{c.title || 'Untitled'}</span>
                  <span
                    className="shrink-0 text-[11px] text-[var(--muted-foreground)]"
                    title={new Date(c.updatedAt).toLocaleString()}
                  >
                    {relativeTime(c.updatedAt)}
                  </span>
                </div>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

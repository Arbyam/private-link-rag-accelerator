/**
 * Two-column application shell (T090).
 *
 * Server component: receives the pre-fetched conversation list and the
 * resolved session user from the root layout. The interactive bits
 * (active-route highlight, sign-out form) are delegated to client-side
 * pieces only where required.
 *
 * Layout:
 *   ┌──────────────────────────────────────────────┐
 *   │ ┌──────────┐ ┌─────────────────────────────┐ │
 *   │ │  rail    │ │  page content (children)    │ │
 *   │ │ ~280px   │ │                             │ │
 *   │ └──────────┘ └─────────────────────────────┘ │
 *   └──────────────────────────────────────────────┘
 */
import Link from 'next/link';
import type { ReactNode } from 'react';
import type { ConversationSummary } from '@/lib/api';
import { signOut } from '@/lib/auth';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { ConversationList } from './ConversationList';

export interface AppShellProps {
  children: ReactNode;
  conversations: ConversationSummary[];
  user: {
    name?: string | null;
    email?: string | null;
    displayName?: string | null;
  };
}

export function AppShell({ children, conversations, user }: AppShellProps) {
  const displayName = user.displayName ?? user.name ?? user.email ?? 'Signed in';

  async function handleSignOut() {
    'use server';
    await signOut({ redirectTo: '/signin' });
  }

  return (
    <div className="flex h-screen w-full overflow-hidden bg-[var(--background)] text-[var(--foreground)]">
      <aside
        aria-label="Application sidebar"
        className="flex w-[280px] shrink-0 flex-col border-r border-[var(--border)] bg-[var(--muted)]/40"
      >
        {/* Brand + new conversation */}
        <div className="flex flex-col gap-3 border-b border-[var(--border)] px-4 py-4">
          <Link
            href="/"
            className="block rounded-sm text-sm font-semibold tracking-tight text-[var(--foreground)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
          >
            Private RAG Accelerator
          </Link>
          <Button asChild size="sm" className="w-full">
            <Link href="/chat">+ New conversation</Link>
          </Button>
        </div>

        {/* Conversation list */}
        <ScrollArea className="min-h-0 flex-1">
          <ConversationList conversations={conversations} />
        </ScrollArea>

        {/* User + sign-out */}
        <div className="flex flex-col gap-2 border-t border-[var(--border)] px-4 py-3">
          <div className="min-w-0">
            <span
              className="block truncate text-sm font-medium text-[var(--foreground)]"
              title={displayName}
            >
              {displayName}
            </span>
            {user.email && user.email !== displayName ? (
              <span
                className="block truncate text-xs text-[var(--muted-foreground)]"
                title={user.email}
              >
                {user.email}
              </span>
            ) : null}
          </div>
          <form action={handleSignOut}>
            <Button type="submit" variant="outline" size="sm" className="w-full">
              Sign out
            </Button>
          </form>
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col overflow-hidden">{children}</section>
    </div>
  );
}

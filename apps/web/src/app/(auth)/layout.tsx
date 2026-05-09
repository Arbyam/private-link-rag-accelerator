/**
 * Layout for the unauthenticated `(auth)` route group.
 *
 * Renders a minimal centered shell — no chat chrome, no nav. Used by
 * `/signin` and `/error`. The root `app/layout.tsx` still wraps this, so
 * we only own the inner page frame here.
 */
import type { ReactNode } from 'react';

export default function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-neutral-50 px-4 py-12 dark:bg-neutral-950">
      <div className="w-full max-w-md">{children}</div>
    </main>
  );
}

/**
 * Edge-runtime-safe Auth.js v5 configuration.
 *
 * This file MUST NOT import any Node-only modules (no `crypto`, no providers
 * that require `jose`, no DB adapters). It is consumed by `middleware.ts`
 * which executes in the Edge runtime. Provider wiring lives in `auth.ts`.
 *
 * Pattern reference: https://authjs.dev/guides/edge-compatibility
 * (Phase 2b research.md D7).
 */
import type { NextAuthConfig } from 'next-auth';

export const authConfig = {
  // Stateless JWTs — Container Apps web revisions are horizontally scaled
  // and we don't host a session DB.
  session: { strategy: 'jwt' },
  // Auth.js routes — custom pages live under the `(auth)` route group.
  pages: {
    signIn: '/signin',
    error: '/error',
  },
  // Edge-safe callbacks only. Node-only logic (group claim parsing, token
  // refresh) lives in `auth.ts`.
  callbacks: {
    /**
     * Edge-runtime gate used by middleware. Any authenticated session is
     * permitted past middleware; route-level role checks happen server-side.
     */
    authorized({ auth, request }) {
      const isLoggedIn = !!auth?.user;
      const { pathname } = request.nextUrl;

      // Public surfaces — explicitly allowed for unauthenticated users.
      // FR-006: anonymous users are rejected from every other route.
      const isPublic =
        pathname.startsWith('/signin') ||
        pathname.startsWith('/error') ||
        pathname.startsWith('/api/auth') ||
        pathname.startsWith('/_next') ||
        pathname.startsWith('/favicon');

      if (isPublic) return true;
      // Returning `false` from `authorized` triggers a redirect to the
      // configured `pages.signIn` with `callbackUrl` preserved.
      return isLoggedIn;
    },
  },
  // Providers are added in `auth.ts` (Node runtime only).
  providers: [],
} satisfies NextAuthConfig;

/**
 * Edge-runtime auth middleware (Auth.js v5 pattern).
 *
 * Imports ONLY `auth.config.ts` so it stays Edge-compatible. Provider wiring
 * (which uses Node-only `Buffer` for id_token decoding + the refresh fetch)
 * is in `lib/auth.ts` and runs only on the server.
 */
import NextAuth from 'next-auth';
import { authConfig } from './auth.config';

export const { auth: middleware } = NextAuth(authConfig);

export const config = {
  // Run on every route except static assets and Auth.js internal endpoints.
  // The `authorized` callback in auth.config.ts does the actual gating.
  matcher: ['/((?!api/auth|_next/static|_next/image|favicon.ico|login|.*\\..*).*)'],
};

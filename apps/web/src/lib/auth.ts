/**
 * Auth.js v5 (NextAuth) configuration for Microsoft Entra ID.
 *
 * Implements T043:
 *   - Tenant-scoped Microsoft Entra provider via `AUTH_MICROSOFT_ENTRA_ID_*`
 *   - Group restriction via `ALLOWED_USER_GROUP_OBJECT_IDS` (D8)
 *   - JWT session strategy (stateless — no DB on the web tier)
 *   - Refresh-token flow so access tokens forwarded to the API stay fresh
 *   - Edge-safe split: shared bits live in `../auth.config.ts`
 *
 * Required env (see `.env.example`):
 *   AUTH_SECRET
 *   AUTH_MICROSOFT_ENTRA_ID_ID
 *   AUTH_MICROSOFT_ENTRA_ID_SECRET
 *   AUTH_MICROSOFT_ENTRA_ID_ISSUER          (https://login.microsoftonline.com/{tenant}/v2.0)
 *   AUTH_TRUST_HOST=true                    (behind ACA internal ingress)
 *   ALLOWED_USER_GROUP_OBJECT_IDS           (comma-separated; empty disables the gate)
 *   ADMIN_GROUP_OBJECT_ID                   (single group object id)
 */
import NextAuth, { type DefaultSession } from 'next-auth';
import type { JWT } from 'next-auth/jwt';
import MicrosoftEntraID from 'next-auth/providers/microsoft-entra-id';
import { authConfig } from '../auth.config';

declare module 'next-auth' {
  interface Session {
    accessToken?: string;
    error?: 'RefreshAccessTokenError';
    user: {
      oid?: string;
      displayName?: string;
      groups?: string[];
      role?: 'admin' | 'user';
    } & DefaultSession['user'];
  }
}

declare module 'next-auth/jwt' {
  interface JWT {
    accessToken?: string;
    refreshToken?: string;
    accessTokenExpires?: number;
    oid?: string;
    displayName?: string;
    groups?: string[];
    role?: 'admin' | 'user';
    error?: 'RefreshAccessTokenError';
  }
}

function parseCsv(value: string | undefined): string[] {
  if (!value) return [];
  return value
    .split(',')
    .map((g) => g.trim())
    .filter(Boolean);
}

function computeRole(groups: string[] | undefined): 'admin' | 'user' {
  const adminGroup = process.env.ADMIN_GROUP_OBJECT_ID?.trim();
  if (adminGroup && groups?.includes(adminGroup)) return 'admin';
  return 'user';
}

/**
 * Group-restriction gate (research.md D8).
 *
 * If `ALLOWED_USER_GROUP_OBJECT_IDS` is set and non-empty, the user's
 * Entra `groups` claim MUST intersect at least one allowed group, otherwise
 * sign-in is rejected. If the env var is empty/unset, all tenant users in
 * the configured tenant are admitted.
 */
function isGroupAllowed(groups: string[] | undefined): boolean {
  const allowed = parseCsv(process.env.ALLOWED_USER_GROUP_OBJECT_IDS);
  if (allowed.length === 0) return true;
  if (!groups || groups.length === 0) return false;
  return groups.some((g) => allowed.includes(g));
}

interface EntraTokenResponse {
  access_token: string;
  refresh_token?: string;
  expires_in: number;
  token_type: string;
  scope?: string;
  error?: string;
  error_description?: string;
}

/**
 * Microsoft Entra refresh-token flow. Called from the `jwt` callback
 * when the cached access token is within 60s of expiry.
 */
async function refreshAccessToken(
  refreshToken: string
): Promise<{ accessToken: string; refreshToken: string; accessTokenExpires: number }> {
  const issuer = process.env.AUTH_MICROSOFT_ENTRA_ID_ISSUER;
  const clientId = process.env.AUTH_MICROSOFT_ENTRA_ID_ID;
  const clientSecret = process.env.AUTH_MICROSOFT_ENTRA_ID_SECRET;
  if (!issuer || !clientId || !clientSecret) {
    throw new Error('Missing Entra ID env (issuer/client_id/client_secret)');
  }

  // The v2.0 issuer URL ends in `/v2.0`. The token endpoint sits one level up.
  const tokenUrl = `${issuer.replace(/\/v2\.0\/?$/, '')}/oauth2/v2.0/token`;

  const body = new URLSearchParams({
    grant_type: 'refresh_token',
    client_id: clientId,
    client_secret: clientSecret,
    refresh_token: refreshToken,
    scope: 'openid profile email offline_access',
  });

  const res = await fetch(tokenUrl, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  });
  const data = (await res.json()) as EntraTokenResponse;
  if (!res.ok) {
    throw new Error(data.error_description ?? data.error ?? `refresh failed (${res.status})`);
  }
  return {
    accessToken: data.access_token,
    refreshToken: data.refresh_token ?? refreshToken,
    accessTokenExpires: Date.now() + data.expires_in * 1000,
  };
}

export const { auth, handlers, signIn, signOut } = NextAuth({
  ...authConfig,
  providers: [
    MicrosoftEntraID({
      clientId: process.env.AUTH_MICROSOFT_ENTRA_ID_ID,
      clientSecret: process.env.AUTH_MICROSOFT_ENTRA_ID_SECRET,
      issuer: process.env.AUTH_MICROSOFT_ENTRA_ID_ISSUER,
      authorization: {
        // `offline_access` -> refresh tokens; `User.Read` -> /me API.
        // `groups` are emitted in the ID/Access token via the app
        // registration's optional claims + group claims configuration.
        params: { scope: 'openid profile email offline_access User.Read' },
      },
    }),
  ],
  callbacks: {
    ...authConfig.callbacks,

    /**
     * Reject sign-in for users outside the allowed Entra groups.
     * Returning `false` causes Auth.js to redirect to the error page.
     */
    async signIn({ account, profile }) {
      // Only enforce on Entra logins.
      if (account?.provider !== 'microsoft-entra-id') return false;

      const groups = extractGroups(profile, account);
      return isGroupAllowed(groups);
    },

    async jwt({ token, account, profile }) {
      // Initial sign-in: persist Entra tokens + identity claims onto the JWT.
      if (account && profile) {
        const groups = extractGroups(profile, account);
        token.accessToken = account.access_token;
        token.refreshToken = account.refresh_token;
        token.accessTokenExpires = account.expires_at
          ? account.expires_at * 1000
          : Date.now() + 60 * 60 * 1000;
        token.oid =
          ((profile as Record<string, unknown>).oid as string | undefined) ??
          ((profile as Record<string, unknown>).sub as string | undefined);
        token.displayName =
          ((profile as Record<string, unknown>).name as string | undefined) ??
          ((profile as Record<string, unknown>).preferred_username as string | undefined);
        token.groups = groups;
        token.role = computeRole(groups);
        return token;
      }

      // Subsequent calls: refresh if expired (or about to expire).
      const expiresAt = token.accessTokenExpires ?? 0;
      if (Date.now() < expiresAt - 60_000) {
        return token;
      }
      if (!token.refreshToken) {
        return { ...token, error: 'RefreshAccessTokenError' };
      }
      try {
        const refreshed = await refreshAccessToken(token.refreshToken);
        return {
          ...token,
          accessToken: refreshed.accessToken,
          refreshToken: refreshed.refreshToken,
          accessTokenExpires: refreshed.accessTokenExpires,
          error: undefined,
        };
      } catch {
        return { ...token, error: 'RefreshAccessTokenError' };
      }
    },

    async session({ session, token }) {
      session.accessToken = token.accessToken;
      session.error = token.error;
      session.user.oid = token.oid;
      session.user.displayName = token.displayName;
      session.user.groups = token.groups;
      session.user.role = token.role ?? 'user';
      return session;
    },
  },
});

/**
 * Pull the `groups` claim out of the Entra ID token / profile. Entra emits
 * groups in the ID token (or access token) when the app registration has
 * group claims configured. When the user is a member of too many groups,
 * Entra emits `_claim_names` / `_claim_sources` instead — that overage
 * scenario is out of scope here; configure the app to emit only security
 * groups assigned to the application (see deployment docs).
 */
function extractGroups(
  profile: unknown,
  account: { id_token?: string | null } | null | undefined
): string[] {
  const fromProfile = (profile as { groups?: unknown } | null | undefined)?.groups;
  if (Array.isArray(fromProfile)) {
    return fromProfile.filter((g): g is string => typeof g === 'string');
  }
  // Fallback: decode the id_token payload if Auth.js didn't lift `groups` onto profile.
  const idToken = account?.id_token;
  if (typeof idToken === 'string' && idToken.split('.').length === 3) {
    try {
      const payload = JSON.parse(Buffer.from(idToken.split('.')[1], 'base64').toString('utf8')) as {
        groups?: unknown;
      };
      if (Array.isArray(payload.groups)) {
        return payload.groups.filter((g): g is string => typeof g === 'string');
      }
    } catch {
      /* ignore */
    }
  }
  return [];
}

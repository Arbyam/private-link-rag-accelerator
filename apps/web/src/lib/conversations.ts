/**
 * Server-side helper for fetching the caller's conversations.
 *
 * Used by the root layout (RSC) to render the left-rail conversation
 * list. Tolerates auth/transport failures by returning an empty list —
 * the layout must remain renderable even if the API is briefly down.
 */
import 'server-only';
import { ApiError, createApiClient, type ConversationSummary } from './api';

/**
 * Fetch the current user's conversations using the supplied bearer
 * token. Returns an empty array on 401 (middleware should have already
 * redirected) or any transport/parse failure.
 */
export async function listConversations(
  token: string | undefined,
  limit = 25
): Promise<ConversationSummary[]> {
  if (!token) return [];
  const client = createApiClient({ token });
  try {
    const res = await client.listConversations({ limit });
    return res.items ?? [];
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      return [];
    }
    // Don't crash the shell on a flaky API call — the user can still
    // navigate to /chat and start a fresh conversation.
    console.error('listConversations failed:', err);
    return [];
  }
}

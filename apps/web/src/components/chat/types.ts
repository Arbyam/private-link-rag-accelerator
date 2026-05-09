import type { components } from '@/lib/types/api';

/**
 * Citation as returned by the API. Re-exported for convenient component
 * imports without depending on the deeply-nested generated path.
 */
export type Citation = components['schemas']['Citation'];

/**
 * A single chat message rendered by ChatPane / MessageBubble. This is the
 * client-side shape; the data-fetching hook (T087 useChat) maps API turns
 * into this type.
 */
export type ChatMessage = {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  citations?: Citation[];
  /** True only for the trailing assistant message while tokens stream in. */
  isStreaming?: boolean;
};

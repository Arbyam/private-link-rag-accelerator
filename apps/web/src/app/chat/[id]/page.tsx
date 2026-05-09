import { notFound, redirect } from 'next/navigation';
import { auth } from '@/lib/auth';
import { getServerApiClient, ApiError } from '@/lib/api';
import { ChatClient } from '@/components/chat/ChatClient';
import type { ChatMessage } from '@/components/chat/types';
import type { Conversation, Turn } from '@/lib/api';

/**
 * Existing conversation page (T087).
 *
 * Server component: loads the conversation server-side using the user's
 * access token, maps API turns into `ChatMessage`, and hands off to the
 * client shell. 404 for missing / forbidden conversations.
 */
export default async function ExistingChatPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

  const session = await auth();
  if (!session?.accessToken) {
    redirect('/signin');
  }

  let conversation: Conversation;
  try {
    const client = await getServerApiClient();
    conversation = await client.getConversation(id);
  } catch (err) {
    if (err instanceof ApiError && (err.status === 404 || err.status === 403)) {
      notFound();
    }
    throw err;
  }

  const initialMessages: ChatMessage[] = conversation.turns.map(turnToMessage);
  const apiBaseUrl =
    process.env.NEXT_PUBLIC_API_BASE_URL ?? process.env.API_BASE_URL ?? '';

  return (
    <main className="h-[100dvh]">
      <ChatClient
        initialConversationId={conversation.id}
        initialMessages={initialMessages}
        accessToken={session.accessToken}
        apiBaseUrl={apiBaseUrl}
      />
    </main>
  );
}

function turnToMessage(turn: Turn): ChatMessage {
  return {
    id: turn.turnId,
    role: turn.role,
    content: turn.content,
    citations: turn.citations,
  };
}

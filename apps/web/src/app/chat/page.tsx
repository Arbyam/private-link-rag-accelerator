import { redirect } from 'next/navigation';
import { auth } from '@/lib/auth';
import { ChatClient } from '@/components/chat/ChatClient';

/**
 * New conversation entry point (T087).
 *
 * Server component: resolves the Auth.js session, then renders the client
 * shell with no initial conversation. After the first message, the
 * `done` SSE event surfaces the freshly minted conversation id and the
 * client `router.replace`s to `/chat/{id}`.
 */
export default async function NewChatPage() {
  const session = await auth();
  if (!session?.accessToken) {
    redirect('/signin');
  }
  const apiBaseUrl =
    process.env.NEXT_PUBLIC_API_BASE_URL ?? process.env.API_BASE_URL ?? '';

  return (
    <main className="h-[100dvh]">
      <ChatClient
        initialConversationId={null}
        initialMessages={[]}
        accessToken={session.accessToken}
        apiBaseUrl={apiBaseUrl}
      />
    </main>
  );
}

import type { Metadata } from 'next';
import { AppShell } from '@/components/shell/AppShell';
import { auth } from '@/lib/auth';
import { listConversations } from '@/lib/conversations';
import './globals.css';

export const metadata: Metadata = {
  title: 'Private RAG Accelerator',
  description: 'Enterprise document chat with private Azure services',
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // Resolve the session in the root RSC. When unauthenticated (e.g. on
  // /signin), we bypass the shell entirely so the (auth) layout can
  // render its own centered frame without sidebar chrome.
  const session = await auth();
  const signedIn = !!session?.user;

  const conversations = signedIn ? await listConversations(session?.accessToken) : [];

  return (
    <html lang="en">
      <body className="antialiased">
        {signedIn ? (
          <AppShell
            conversations={conversations}
            user={{
              name: session.user.name,
              email: session.user.email,
              displayName: session.user.displayName,
            }}
          >
            {children}
          </AppShell>
        ) : (
          children
        )}
      </body>
    </html>
  );
}

/**
 * Sign-in page (T086).
 *
 * Server component that posts to Auth.js's built-in sign-in endpoint via
 * the server-action `signIn()` helper. We avoid the client-side helper so
 * this page works without JS and stays a pure server component.
 *
 * Provider id `microsoft-entra-id` matches the provider configured in
 * `apps/web/src/lib/auth.ts`.
 */
import { redirect } from 'next/navigation';
import { auth, signIn } from '@/lib/auth';

interface SignInPageProps {
  // Next 15: searchParams is a Promise.
  searchParams: Promise<{ callbackUrl?: string | string[] }>;
}

const PROVIDER_ID = 'microsoft-entra-id';

export default async function SignInPage({ searchParams }: SignInPageProps) {
  const params = await searchParams;
  const rawCallback = params.callbackUrl;
  const callbackUrl = Array.isArray(rawCallback) ? rawCallback[0] : rawCallback;

  // If already signed in, bounce to the requested page (or root).
  const session = await auth();
  if (session?.user) {
    redirect(callbackUrl ?? '/');
  }

  async function handleSignIn() {
    'use server';
    await signIn(PROVIDER_ID, { redirectTo: callbackUrl ?? '/' });
  }

  return (
    <section
      aria-labelledby="signin-heading"
      className="rounded-xl border border-neutral-200 bg-white p-8 shadow-sm dark:border-neutral-800 dark:bg-neutral-900"
    >
      <header className="mb-6 space-y-2">
        <h1
          id="signin-heading"
          className="text-2xl font-semibold tracking-tight text-neutral-900 dark:text-neutral-50"
        >
          Sign in to Private RAG Accelerator
        </h1>
        <p className="text-sm leading-relaxed text-neutral-600 dark:text-neutral-400">
          This workspace is protected by your organization&rsquo;s Microsoft Entra ID. Use your work
          account to continue. Anonymous access is not permitted.
        </p>
      </header>

      <form action={handleSignIn}>
        <button
          type="submit"
          className="inline-flex w-full items-center justify-center gap-2 rounded-md bg-neutral-900 px-4 py-2.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-neutral-800 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-neutral-900 disabled:opacity-60 dark:bg-neutral-50 dark:text-neutral-900 dark:hover:bg-neutral-200 dark:focus-visible:outline-neutral-50"
          aria-label="Sign in with Microsoft Entra ID"
        >
          <MicrosoftMark aria-hidden="true" />
          <span>Sign in with Microsoft Entra ID</span>
        </button>
      </form>

      <p className="mt-6 text-xs text-neutral-500 dark:text-neutral-500">
        By continuing you agree to your organization&rsquo;s acceptable use policies.
      </p>
    </section>
  );
}

function MicrosoftMark(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" {...props}>
      <rect x="0" y="0" width="7" height="7" fill="#F25022" />
      <rect x="9" y="0" width="7" height="7" fill="#7FBA00" />
      <rect x="0" y="9" width="7" height="7" fill="#00A4EF" />
      <rect x="9" y="9" width="7" height="7" fill="#FFB900" />
    </svg>
  );
}

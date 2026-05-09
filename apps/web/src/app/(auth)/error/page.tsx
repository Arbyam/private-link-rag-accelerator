/**
 * Auth error page (T086).
 *
 * Surfaced by Auth.js whenever sign-in fails — e.g. Entra group restriction
 * rejected the user (`AccessDenied`), provider misconfiguration
 * (`Configuration`), or a verification failure (`Verification`).
 */
import Link from 'next/link';

interface AuthErrorPageProps {
  searchParams: Promise<{ error?: string | string[] }>;
}

type KnownError =
  | 'Configuration'
  | 'AccessDenied'
  | 'Verification'
  | 'OAuthSignin'
  | 'OAuthCallback'
  | 'OAuthAccountNotLinked'
  | 'Callback'
  | 'Default';

const ERROR_MESSAGES: Record<KnownError, { title: string; body: string }> = {
  Configuration: {
    title: 'Sign-in is misconfigured',
    body: 'The application is missing required Microsoft Entra ID configuration. Please contact your administrator.',
  },
  AccessDenied: {
    title: 'Access denied',
    body: 'Your account is not authorized to use this workspace. Ask an administrator to add you to the allowed Entra ID security group.',
  },
  Verification: {
    title: 'Verification failed',
    body: 'The sign-in link is invalid or has expired. Please try again.',
  },
  OAuthSignin: {
    title: 'Sign-in failed',
    body: 'We could not start the Microsoft Entra ID sign-in. Please try again.',
  },
  OAuthCallback: {
    title: 'Sign-in failed',
    body: 'Microsoft Entra ID returned an error during sign-in. Please try again.',
  },
  OAuthAccountNotLinked: {
    title: 'Account not linked',
    body: 'This identity is already associated with a different sign-in method. Please use your original sign-in method.',
  },
  Callback: {
    title: 'Sign-in failed',
    body: 'Something went wrong while completing sign-in. Please try again.',
  },
  Default: {
    title: 'Sign-in failed',
    body: 'An unexpected error occurred while signing you in. Please try again.',
  },
};

function resolveError(raw: string | undefined): { title: string; body: string; code: string } {
  const code = (raw ?? 'Default') as KnownError;
  const entry = ERROR_MESSAGES[code] ?? ERROR_MESSAGES.Default;
  return { ...entry, code };
}

export default async function AuthErrorPage({ searchParams }: AuthErrorPageProps) {
  const params = await searchParams;
  const raw = Array.isArray(params.error) ? params.error[0] : params.error;
  const { title, body, code } = resolveError(raw);

  return (
    <section
      aria-labelledby="auth-error-heading"
      className="rounded-xl border border-neutral-200 bg-white p-8 shadow-sm dark:border-neutral-800 dark:bg-neutral-900"
    >
      <header className="mb-4 space-y-2">
        <p className="text-xs font-medium uppercase tracking-wide text-red-600 dark:text-red-400">
          Authentication error
        </p>
        <h1
          id="auth-error-heading"
          className="text-2xl font-semibold tracking-tight text-neutral-900 dark:text-neutral-50"
        >
          {title}
        </h1>
      </header>

      <p className="text-sm leading-relaxed text-neutral-600 dark:text-neutral-400">{body}</p>

      <p className="mt-2 text-xs text-neutral-500 dark:text-neutral-500">
        Reference code: <code className="font-mono">{code}</code>
      </p>

      <div className="mt-6">
        <Link
          href="/signin"
          className="inline-flex items-center justify-center rounded-md border border-neutral-300 bg-white px-4 py-2 text-sm font-medium text-neutral-900 shadow-sm transition-colors hover:bg-neutral-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-neutral-900 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-50 dark:hover:bg-neutral-800 dark:focus-visible:outline-neutral-50"
        >
          Back to sign in
        </Link>
      </div>
    </section>
  );
}

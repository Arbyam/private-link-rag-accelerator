import Link from 'next/link';

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-8 p-24">
      <div className="flex flex-col items-center gap-4 text-center">
        <h1 className="text-4xl font-bold">Private RAG Accelerator</h1>
        <p className="text-lg text-gray-600">
          Enterprise document chat powered by Azure AI
        </p>
      </div>
      <Link
        href="/chat"
        className="inline-flex items-center rounded-md bg-[var(--foreground)] px-5 py-2.5 text-sm font-semibold text-[var(--background)] shadow-sm transition-colors hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]"
      >
        Start a chat →
      </Link>
    </main>
  );
}

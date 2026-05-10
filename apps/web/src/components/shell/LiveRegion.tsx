'use client';

/**
 * Visually-hidden ARIA live region for screen-reader announcements (T089).
 *
 * Use the {@link useAnnouncer} hook to push messages from anywhere in the
 * tree. A single mounted `<LiveRegion />` (in `AppShell`) consumes them
 * and surfaces them to assistive tech without affecting layout.
 */
import * as React from 'react';

type Politeness = 'polite' | 'assertive';

interface Announcement {
  id: number;
  message: string;
  politeness: Politeness;
}

interface AnnouncerContextValue {
  announce: (message: string, politeness?: Politeness) => void;
}

const AnnouncerContext = React.createContext<AnnouncerContextValue | null>(null);

let nextId = 1;

export function AnnouncerProvider({ children }: { children: React.ReactNode }) {
  const [polite, setPolite] = React.useState<Announcement | null>(null);
  const [assertive, setAssertive] = React.useState<Announcement | null>(null);

  const announce = React.useCallback((message: string, politeness: Politeness = 'polite') => {
    if (!message) return;
    const next = { id: nextId++, message, politeness };
    if (politeness === 'assertive') setAssertive(next);
    else setPolite(next);
  }, []);

  const value = React.useMemo(() => ({ announce }), [announce]);

  return (
    <AnnouncerContext.Provider value={value}>
      {children}
      <div
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className="sr-only"
        data-testid="live-region-polite"
      >
        {polite?.message ?? ''}
      </div>
      <div
        role="alert"
        aria-live="assertive"
        aria-atomic="true"
        className="sr-only"
        data-testid="live-region-assertive"
      >
        {assertive?.message ?? ''}
      </div>
    </AnnouncerContext.Provider>
  );
}

export function useAnnouncer(): AnnouncerContextValue {
  const ctx = React.useContext(AnnouncerContext);
  // No-op fallback for trees rendered without the provider (tests, etc.)
  return ctx ?? { announce: () => {} };
}

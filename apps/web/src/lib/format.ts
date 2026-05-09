/**
 * Tiny formatting utilities shared by the UI shell.
 * No runtime deps — keeps the client bundle small.
 */

const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;
const WEEK = 7 * DAY;
const MONTH = 30 * DAY;
const YEAR = 365 * DAY;

/**
 * Returns a short human-readable relative time, e.g. "just now",
 * "5m ago", "2h ago", "3d ago", "2w ago", "4mo ago", "1y ago".
 *
 * Falls back to a locale date string for invalid inputs so the UI
 * never crashes on bad timestamps.
 */
export function relativeTime(input: string | Date | null | undefined): string {
  if (!input) return '';
  const date = input instanceof Date ? input : new Date(input);
  const t = date.getTime();
  if (Number.isNaN(t)) return '';

  const diff = Date.now() - t;
  if (diff < 0) {
    // Future timestamps — just show the date.
    return date.toLocaleDateString();
  }
  if (diff < MINUTE) return 'just now';
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)}m ago`;
  if (diff < DAY) return `${Math.floor(diff / HOUR)}h ago`;
  if (diff < WEEK) return `${Math.floor(diff / DAY)}d ago`;
  if (diff < MONTH) return `${Math.floor(diff / WEEK)}w ago`;
  if (diff < YEAR) return `${Math.floor(diff / MONTH)}mo ago`;
  return `${Math.floor(diff / YEAR)}y ago`;
}

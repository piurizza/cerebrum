const formatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

/** Format an ISO-8601 timestamp (or null) for display, in the user's
 * local timezone and locale. Returns null if there's nothing to show. */
export function formatTimestamp(value: string | null): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  return formatter.format(date);
}

const dateFormatter = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });
const relativeFormatter = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
const DAY_MS = 24 * 60 * 60 * 1000;

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/** "today", "3 days ago", "last week" for recent timestamps, the date
 * itself for older ones. Returns null if there's nothing to show. */
export function formatRelativeDate(
  value: string | null,
  now: Date = new Date(),
): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return null;
  const days = Math.round((startOfDay(date) - startOfDay(now)) / DAY_MS);
  if (Math.abs(days) < 7) return relativeFormatter.format(days, "day");
  if (Math.abs(days) < 28)
    return relativeFormatter.format(Math.round(days / 7), "week");
  return dateFormatter.format(date);
}

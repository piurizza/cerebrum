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

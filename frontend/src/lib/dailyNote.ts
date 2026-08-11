const headingFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: "full",
});

/** The vault-relative folder daily notes live in, configurable at build
 * time via `VITE_DAILY_NOTE_FOLDER` (same `import.meta.env.VITE_*`
 * pattern as `api/client.ts`'s `VITE_API_BASE_URL`). `||`, not `??`: an
 * explicitly-empty env value (a plausible `.env` typo) must also fall
 * back to the default, not produce a leading-slash path. */
function dailyNoteFolder(): string {
  const folder = import.meta.env.VITE_DAILY_NOTE_FOLDER?.trim() || "daily";
  return folder.endsWith("/") ? folder.slice(0, -1) : folder;
}

/** Today's daily-note path, e.g. "daily/2026-08-11.md" -- computed from
 * the browser's *local* calendar day, never UTC. `toISOString()` would
 * convert to UTC first, silently shifting the date near midnight for any
 * timezone not aligned to UTC; the local getters read the wall-clock date
 * the user is actually looking at. Accepts an optional `date` so tests
 * can inject a fixed value instead of depending on wall-clock time. */
export function getTodayNotePath(date: Date = new Date()): string {
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  return `${dailyNoteFolder()}/${yyyy}-${mm}-${dd}.md`;
}

/** Default body for a newly-created daily note: just a date heading, not
 * an empty file. This is a fixed, single-purpose default for this one
 * feature -- not a reusable template mechanism (see the separate,
 * deferred "note templates" roadmap item). */
export function getDailyNoteDefaultBody(date: Date = new Date()): string {
  return `# ${headingFormatter.format(date)}\n\n`;
}

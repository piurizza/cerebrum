import { normalizeFolderEnvVar } from "./envFolder";

const headingFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: "full",
});

/** The vault-relative folder daily notes live in, configurable at build
 * time via `VITE_DAILY_NOTE_FOLDER` (same `import.meta.env.VITE_*`
 * pattern as `api/client.ts`'s `VITE_API_BASE_URL`). Normalization
 * (fallback + slash-trim) is shared with `templates.ts`'s
 * `VITE_TEMPLATES_FOLDER` via `normalizeFolderEnvVar` -- see that
 * function's doc comment for why the trim matters. */
function dailyNoteFolder(): string {
  return normalizeFolderEnvVar(import.meta.env.VITE_DAILY_NOTE_FOLDER, "daily");
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
 * feature -- not the general template mechanism (`lib/templates.ts`),
 * which daily notes deliberately don't go through (see that plan's
 * Scope Boundaries). */
export function getDailyNoteDefaultBody(date: Date = new Date()): string {
  return `# ${headingFormatter.format(date)}\n\n`;
}

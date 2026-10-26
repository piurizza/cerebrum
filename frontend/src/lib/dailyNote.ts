import { vaultFolders } from "./vaultSettings";

const headingFormatter = new Intl.DateTimeFormat(undefined, {
  dateStyle: "full",
});

/** The vault-relative folder daily notes live in, set on the server
 * (`CEREBRUM_DAILY_NOTE_FOLDER`) and read through `vaultSettings.ts`. */
function dailyNoteFolder(): string {
  return vaultFolders().dailyNoteFolder;
}

/** Today's daily-note path, e.g. "daily/2026-08-11.md" -- computed from
 * the browser's *local* calendar day, never UTC. `toISOString()` would
 * convert to UTC first, silently shifting the date near midnight for any
 * timezone not aligned to UTC; the local getters read the wall-clock date
 * the user is actually looking at. Accepts an optional `date` so tests
 * can inject a fixed value instead of depending on wall-clock time. */
export function getTodayNotePath(date: Date = new Date()): string {
  return `${dailyNoteFolder()}/${localIsoDate(date)}.md`;
}

/** The browser's local calendar day as YYYY-MM-DD, never the UTC one (see
 * `getTodayNotePath`): the day a task ticked now is recorded as done. */
export function localIsoDate(date: Date = new Date()): string {
  const yyyy = date.getFullYear();
  const mm = String(date.getMonth() + 1).padStart(2, "0");
  const dd = String(date.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

/** Default body for a newly-created daily note: just a date heading, not
 * an empty file. This is a fixed, single-purpose default for this one
 * feature -- not the general template mechanism (`lib/templates.ts`),
 * which daily notes deliberately don't go through (see that plan's
 * Scope Boundaries). */
export function getDailyNoteDefaultBody(date: Date = new Date()): string {
  return `# ${getDailyNoteHeading(date)}\n\n`;
}

/** The text of a new daily note's heading, without the `# `: the long
 * local date. A task added from the Tasks page sends it, so a daily note
 * the server creates for the task reads like one the Today button made. */
export function getDailyNoteHeading(date: Date = new Date()): string {
  return headingFormatter.format(date);
}

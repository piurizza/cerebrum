import { ApiError } from "../api/client";

/** A task line as the backend reads one (`_TASK_LINE` in
 * backend/src/cerebrum/tasks/markers.py): indentation, a `-`, `*` or `+`
 * bullet, a checkbox and the text. Only the checkbox is read here; the
 * done marker stays part of the text, which the server takes either way. */
// `s`, so the text may hold a U+2028, which doesn't end a line here.
const TASK_LINE = /^[ \t]*[-*+] \[([ xX])\] (.*)$/s;

/** Whether `markdown` has at least one line that looks like a task. */
export function hasTaskLine(markdown: string): boolean {
  return markdown.split("\n").some((line) => TASK_LINE.test(line));
}

/** The task on 1-based `line` of a note's raw content (frontmatter
 * included, lines split on `\n` only), or null when that line isn't a
 * task. The text is as written, trailing whitespace (and a CRLF's `\r`)
 * removed, which is what a tick or untick names the task by. */
export function taskOnLine(
  content: string,
  line: number,
): { checked: boolean; text: string } | null {
  return taskInLines(splitLines(content), line);
}

/** A note's raw content split into the lines `taskInLines` reads: on `\n`
 * only. */
export function splitLines(content: string): string[] {
  return content.split("\n");
}

/** `taskOnLine` for content already split with `splitLines`, so a caller
 * reading many lines of one note splits it once. */
export function taskInLines(
  lines: readonly string[],
  line: number,
): { checked: boolean; text: string } | null {
  if (!Number.isInteger(line) || line < 1 || line > lines.length) return null;
  const match = TASK_LINE.exec(lines[line - 1].replace(/\r$/, ""));
  if (!match) return null;
  return { checked: match[1] !== " ", text: match[2].trimEnd() };
}

/** Shown when a tick or untick is refused because the task isn't where it
 * was (409) or its note is gone (404); the caller reloads what it shows. */
export const TASK_CHANGED_MESSAGE =
  "This task changed since it was loaded, so nothing was written. Reloaded to show it as it is now.";

/** Whether a failed tick or untick means the task moved or its note is
 * gone, rather than any other failure. */
export function isTaskChangedError(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 409 || err.status === 404);
}

// What the Tasks page shows of the lists the server sends: the filters it
// narrows them by, all applied in the browser, and the orders it keeps.
import type { TaskItem } from "../types/note";
import { localIsoDate } from "./dailyNote";
import { describeChips, noteMatchesTags, type TagChip } from "./tagQuery";

/** How many days the Done tab looks back over, today included. */
export const DONE_LIST_DAYS = 14;

export interface TaskFilterState {
  /** The shared tag selection, matched against the tags of a task's note. */
  chips: readonly TagChip[];
  /** A folder, its subfolders included; empty for every folder. */
  folder: string;
  /** Words that must all appear in the task's text. */
  words: string;
}

export const NO_FILTERS: TaskFilterState = { chips: [], folder: "", words: "" };

/** One task across both lists and the writes made to it: a tick or untick
 * keeps the task on its line. */
export function taskKey(task: Pick<TaskItem, "path" | "line">): string {
  return `${task.path}\n${task.line}`;
}

function folderOf(path: string): string {
  const slash = path.lastIndexOf("/");
  return slash === -1 ? "" : path.slice(0, slash);
}

/** Every folder holding a task, with the folders above it, which hold
 * those tasks too, sorted. */
export function taskFolders(tasks: readonly TaskItem[]): string[] {
  const folders = new Set<string>();
  for (const task of tasks) {
    const segments = folderOf(task.path).split("/").filter(Boolean);
    for (let i = 1; i <= segments.length; i++) {
      folders.add(segments.slice(0, i).join("/"));
    }
  }
  return [...folders].sort((a, b) => a.localeCompare(b));
}

function filterWords(words: string): string[] {
  return words.toLowerCase().split(/\s+/).filter(Boolean);
}

export function taskMatchesFilters(task: TaskItem, filters: TaskFilterState): boolean {
  if (!noteMatchesTags(task.tags, filters.chips)) return false;
  if (filters.folder && !task.path.startsWith(`${filters.folder}/`)) return false;
  const text = task.text.toLowerCase();
  return filterWords(filters.words).every((word) => text.includes(word));
}

export function hasActiveFilters(filters: TaskFilterState): boolean {
  return (
    filters.chips.length > 0 ||
    filters.folder !== "" ||
    filterWords(filters.words).length > 0
  );
}

/** The active filters as an empty list names them:
 * `#garden, folder home, “seed potatoes”`. */
export function describeTaskFilters(filters: TaskFilterState): string {
  const words = filterWords(filters.words).length > 0;
  return [
    filters.chips.length > 0 ? describeChips(filters.chips) : "",
    filters.folder ? `folder ${filters.folder}` : "",
    words ? `“${filters.words.trim().split(/\s+/).join(" ")}”` : "",
  ]
    .filter(Boolean)
    .join(", ");
}

// Compared as the server's `ORDER BY` compares them, by code unit rather
// than by locale, so a list put back together here keeps the server's order.
function compareText(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/** The open list's order, as `GET /api/tasks` sends it. */
export function byPathAndLine(a: TaskItem, b: TaskItem): number {
  return compareText(a.path, b.path) || a.line - b.line;
}

/** The done list's order, as `GET /api/tasks/done` sends it: newest done
 * date first, then by note and line within a day. */
export function byDoneDateDesc(a: TaskItem, b: TaskItem): number {
  return compareText(b.done_date ?? "", a.done_date ?? "") || byPathAndLine(a, b);
}

/** The earliest done date the Done tab lists: today and the 13 days
 * before it, by the browser's calendar. */
export function doneListSince(today: Date = new Date()): string {
  return localIsoDate(
    new Date(
      today.getFullYear(),
      today.getMonth(),
      today.getDate() - (DONE_LIST_DAYS - 1),
    ),
  );
}

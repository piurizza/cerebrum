import type { NoteMeta } from "../types/note";

/** Builds a minimal `NoteMeta` fixture -- `tags`/`created`/`updated` default
 * to their "unset" values since most tests only care about `path`/`title`.
 * `title` defaults to `path` when a test doesn't care what it displays. */
export function makeNoteMeta(path: string, title: string = path): NoteMeta {
  return { path, title, tags: [], created: null, updated: null };
}

import type { NoteMeta } from "../types/note";

/** Builds a minimal `NoteMeta` fixture -- `tags`/`created`/`updated` default
 * to their "unset" values since most tests only care about `path`/`title`.
 * `title` defaults to `path` when a test doesn't care what it displays. */
export function makeNoteMeta(path: string, title: string = path): NoteMeta {
  return { path, title, tags: [], created: null, updated: null };
}

/** `navigator.onLine` has no setter -- jsdom implements it as a read-only
 * getter, so tests that need to simulate connectivity changes have to
 * redefine the property via `Object.defineProperty` instead of a plain
 * assignment. Shared here since `AuthContext` and `OfflineContext` both
 * need to drive it in their tests. */
export function setNavigatorOnLine(value: boolean): void {
  Object.defineProperty(window.navigator, "onLine", {
    configurable: true,
    value,
  });
}

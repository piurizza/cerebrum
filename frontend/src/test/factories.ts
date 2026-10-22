import { resetVaultFoldersForTests, VAULT_SETTINGS_KEY } from "../lib/vaultSettings";
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

/** Seeds the cached vault settings as if the server last reported
 * `read_only: readOnly` (or clears them, for `null` = never fetched), and
 * drops the in-memory copy so the next read picks it up. Call before
 * rendering: it does not notify mounted subscribers. */
export function setCachedVaultReadOnly(readOnly: boolean | null): void {
  if (readOnly === null) {
    window.localStorage.removeItem(VAULT_SETTINGS_KEY);
  } else {
    window.localStorage.setItem(
      VAULT_SETTINGS_KEY,
      JSON.stringify({ read_only: readOnly }),
    );
  }
  resetVaultFoldersForTests();
}

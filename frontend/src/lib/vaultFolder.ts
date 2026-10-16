/** Normalize a vault-relative folder name: trim, fall back to `fallback`
 * on a missing/empty value, and strip both leading and trailing slashes.
 * Used for every configurable folder the app reads (`vaultSettings.ts`'s
 * daily-notes and templates folders) so the leading-slash fix below only
 * has to exist once.
 *
 * The server already normalizes these values (`Settings` in the backend),
 * so this is defense in depth for what the app actually reads them from:
 * a `localStorage` copy that could be stale, hand-edited, or written by an
 * older server.
 *
 * `||`, not `??`: an explicitly-empty value must also fall back to
 * `fallback`, not produce a leading-slash path. Strips *both* leading and
 * trailing slashes, not just trailing: a leading slash (e.g. `/journal`)
 * would otherwise make the computed path absolute, which the backend's
 * vault-root path join drops the vault prefix for entirely. */
export function normalizeVaultFolder(
  raw: string | undefined,
  fallback: string,
): string {
  const folder = raw?.trim() || fallback;
  const trimmed = folder.replace(/^\/+|\/+$/g, "");
  return trimmed || fallback;
}

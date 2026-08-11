/** Normalize a build-time `VITE_*` folder-name env var: trim, fall back to
 * `fallback` on an unset/empty value, and strip both leading and trailing
 * slashes. Shared by every feature that reads a configurable vault-relative
 * folder name (`dailyNote.ts`'s `VITE_DAILY_NOTE_FOLDER`,
 * `templates.ts`'s `VITE_TEMPLATES_FOLDER`) so the leading-slash fix below
 * only has to exist once.
 *
 * `||`, not `??`: an explicitly-empty env value (a plausible `.env` typo)
 * must also fall back to `fallback`, not produce a leading-slash path.
 * Strips *both* leading and trailing slashes, not just trailing: a leading
 * slash (e.g. `VITE_DAILY_NOTE_FOLDER=/journal`) would otherwise make the
 * computed path absolute, which the backend's vault-root path join drops
 * the vault prefix for entirely -- permanently breaking the feature until
 * the env var is fixed and the frontend rebuilt. */
export function normalizeFolderEnvVar(
  raw: string | undefined,
  fallback: string,
): string {
  const folder = raw?.trim() || fallback;
  const trimmed = folder.replace(/^\/+|\/+$/g, "");
  return trimmed || fallback;
}

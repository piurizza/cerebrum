// Two `localStorage` flags in the auth domain, owned here so their
// storage-denied handling lives in one place (same rationale as
// `offline/sync.ts`'s `readLastSyncedAt` / `persistLastSyncedAt`).
//
// `sessionEstablished` -- "this browser has logged in at least once". It
// replaces `AuthContext`'s old `hasSyncedSnapshot()` (`readLastSyncedAt()
// !== null`) check as the gate for restoring a session from cache when a
// mount refresh fails without a reachable 401/403. It is NOT the same as
// `lastSyncedAt`: `offline/sync.ts`'s `syncVault()` returns early without
// writing `lastSyncedAt` when its `listNotes()` fails (sync.ts lines
// ~42-50) and that write is `try/catch`-guarded, so `lastSyncedAt` can be
// `null` while a valid session and a partial opened-note cache exist; and
// `logout()` must be able to clear the session signal without discarding
// `lastSyncedAt` (the offline banner still shows "notes as of ...").
//
// `loggedOut` -- a one-shot tombstone written by `logout()` and consumed by
// `AuthContext`'s mount effect BEFORE it attempts any refresh. Clearing
// `sessionEstablished` alone does not make an explicit logout stick,
// because a successful mount refresh against the still-valid httpOnly
// refresh cookie would immediately re-`markSessionEstablished()` and
// re-authenticate (the gap the current `logout()` docstring calls known).
// The tombstone is the only client-side mechanism that closes it, given
// there is no server-side session-revoke endpoint.

export const SESSION_ESTABLISHED_KEY = "cerebrum:sessionEstablished";
export const LOGGED_OUT_KEY = "cerebrum:loggedOut";

/** Record that a session exists on this browser. Also clears any stale
 * logout tombstone -- a fresh login/refresh supersedes a prior logout. */
export function markSessionEstablished(): void {
  try {
    window.localStorage.setItem(SESSION_ESTABLISHED_KEY, "1");
    window.localStorage.removeItem(LOGGED_OUT_KEY);
  } catch {
    // Storage can throw (Safari "Block all cookies", sandboxed iframes) --
    // same swallow as ThemeContext / sync.ts. A browser that cannot persist
    // this simply never gets the offline-restore concession, which is safe.
  }
}

/** Forget that a session was established (on a definitive 401/403, or as
 * part of `logout()` alongside `markLoggedOut()`). */
export function clearSessionEstablished(): void {
  try {
    window.localStorage.removeItem(SESSION_ESTABLISHED_KEY);
  } catch {
    // See markSessionEstablished().
  }
}

export function wasSessionEstablished(): boolean {
  try {
    return window.localStorage.getItem(SESSION_ESTABLISHED_KEY) !== null;
  } catch {
    return false;
  }
}

/** Write the one-shot "the user just logged out" tombstone. */
export function markLoggedOut(): void {
  try {
    window.localStorage.setItem(LOGGED_OUT_KEY, "1");
  } catch {
    // See markSessionEstablished(). If this cannot be written, logout
    // reverts to the pre-existing known gap (a reload may re-restore the
    // session via the still-valid cookie) rather than doing anything worse.
  }
}

/** Read-and-remove the logout tombstone. Returns whether it was set. */
export function consumeLoggedOut(): boolean {
  try {
    const value = window.localStorage.getItem(LOGGED_OUT_KEY);
    window.localStorage.removeItem(LOGGED_OUT_KEY);
    return value !== null;
  } catch {
    return false;
  }
}

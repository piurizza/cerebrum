import { getNote, listNotes } from "../api/client";

/** localStorage key this module owns -- read at mount by U4's offline
 * banner as its initial "last known good" timestamp, which is why this
 * has to be `localStorage`, not in-memory state: the flagship offline
 * flow is "go offline, reload, still see the vault", and in-memory state
 * doesn't survive that reload. */
export const LAST_SYNCED_AT_KEY = "cerebrum:lastSyncedAt";

// Small worker pool, not one `fetch` per note in parallel -- a vault can
// have hundreds of notes, and firing them all at once would hammer the
// backend (and, on a slow link, likely blow past the service worker's own
// per-request `networkTimeoutSeconds` in vite.config.ts before most of
// them even get a turn). 5 is an arbitrary middle ground between "fast
// enough to finish a sync in reasonable time" and "polite to the server".
const SYNC_CONCURRENCY = 5;

/**
 * Proactively fetches the entire vault -- the note list and every note's
 * content -- while the app has a live connection (R1: the offline snapshot
 * must cover the whole vault, not just notes the user happened to open).
 *
 * This function doesn't write to any cache itself; it relies entirely on
 * `vite.config.ts`'s `NetworkFirst` runtime-caching rule to intercept each
 * successful `getNote`/`listNotes` fetch and cache the response as a side
 * effect of it succeeding. That also explains the failure handling below:
 * there's no explicit rollback or cleanup for a sync interrupted partway,
 * because Workbox only ever caches responses that actually succeeded --
 * whatever was fetched before the interruption is already safely cached,
 * and the next successful sync naturally supersedes it.
 *
 * Never throws: this is called fire-and-forget from `main.tsx` on
 * successful load (KTD3), and a sync failure must never surface as an
 * unhandled rejection or block the app from rendering. Callers that want
 * to know whether it actually completed should check `lastSyncedAt()`
 * (via `LAST_SYNCED_AT_KEY`) instead.
 */
export async function syncVault(): Promise<void> {
  let notePaths: string[];
  try {
    notePaths = (await listNotes()).map((note) => note.path);
  } catch (err) {
    // Couldn't even get the note list -- nothing to cache this run. Most
    // likely cause is the server being unreachable, which is exactly the
    // condition this whole feature exists to tolerate, so this is an
    // expected, non-exceptional outcome, not a bug -- log at a level that
    // doesn't page anyone but stays visible for debugging.
    console.warn("Vault sync: could not list notes", err);
    return;
  }

  await runWithConcurrency(notePaths, SYNC_CONCURRENCY, async (path) => {
    try {
      await getNote(path);
    } catch (err) {
      // One note failing to fetch (e.g. the connection drops mid-sync)
      // must not affect any other note in this batch -- see the
      // docstring above on why no special partial-sync handling is
      // needed beyond simply not letting this rejection propagate.
      console.warn(`Vault sync: could not cache note "${path}"`, err);
    }
  });

  persistLastSyncedAt();
}

function persistLastSyncedAt(): void {
  try {
    window.localStorage.setItem(LAST_SYNCED_AT_KEY, new Date().toISOString());
  } catch {
    // Persistence is a nice-to-have for this run -- storage can throw
    // (Safari's "Block all cookies", sandboxed iframes, etc.), same
    // rationale as ThemeContext's localStorage write.
  }
}

/** The single reader for `LAST_SYNCED_AT_KEY`, owned by this module
 * alongside the writer above -- `AuthContext` (KTD0's offline-restore
 * check) and `OfflineContext` both need this exact value and both must
 * survive the same storage-denied conditions the write side already
 * defends against, so there's one guarded implementation instead of two
 * call sites independently reimplementing (and risking drifting on) the
 * same try/catch. */
export function readLastSyncedAt(): string | null {
  try {
    return window.localStorage.getItem(LAST_SYNCED_AT_KEY);
  } catch {
    return null;
  }
}

/** Runs `worker` over `items` with at most `limit` calls in flight at
 * once, by having `limit` "lanes" each pull the next item off a shared
 * index as soon as they finish their current one -- simpler than a
 * chunked `Promise.all` over fixed-size batches, and keeps all `limit`
 * lanes continuously busy instead of the whole batch waiting on its
 * slowest member before starting the next one. */
async function runWithConcurrency<T>(
  items: T[],
  limit: number,
  worker: (item: T) => Promise<void>,
): Promise<void> {
  let nextIndex = 0;

  async function lane(): Promise<void> {
    while (nextIndex < items.length) {
      const item = items[nextIndex];
      nextIndex += 1;
      await worker(item);
    }
  }

  const lanes = Array.from({ length: Math.min(limit, items.length) }, () => lane());
  await Promise.all(lanes);
}

import { useOffline } from "../context/OfflineContext";
import { formatTimestamp } from "../lib/formatDate";

/** R5: a clear, glanceable signal that the app is showing a cached
 * snapshot rather than live data, and roughly how stale it is. `role`
 * "status" carries an implicit `aria-live="polite"` so screen readers
 * announce it appearing/disappearing in place (KTD6 -- this is a live UI
 * transition, not a page navigation, so it needs its own live region). */
export function OfflineBanner() {
  const { isOffline, lastSyncedAt } = useOffline();

  if (!isOffline) return null;

  const formatted = formatTimestamp(lastSyncedAt);

  return (
    <p className="offline-banner" role="status">
      {formatted
        ? `Offline -- showing notes as of ${formatted}`
        : "Offline -- some notes may be unavailable"}
    </p>
  );
}

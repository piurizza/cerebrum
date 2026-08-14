import { createContext, type ReactNode, useContext, useEffect, useState } from "react";
import { LAST_SYNCED_AT_KEY } from "../offline/sync";

interface OfflineContextValue {
  /** Mirrors the browser's online/offline state (`navigator.onLine`,
   * kept live via the `online`/`offline` window events -- KTD6). This is
   * a best-effort signal, not a guarantee the server is actually
   * reachable (a machine can be "online" on a LAN with no route to the
   * configured server), but it's the same signal every other browser API
   * exposes and is good enough to gate write actions and show a banner. */
  isOffline: boolean;
  /** ISO-8601 timestamp of the last successful `syncVault()` run (see
   * `LAST_SYNCED_AT_KEY` in `../offline/sync`), or `null` if no sync has
   * ever completed on this device. Read from `localStorage` so it
   * survives a reload -- the flagship offline flow is "go offline,
   * reload, still see the vault". */
  lastSyncedAt: string | null;
}

const OfflineContext = createContext<OfflineContextValue | null>(null);

function readLastSyncedAt(): string | null {
  try {
    return window.localStorage.getItem(LAST_SYNCED_AT_KEY);
  } catch {
    // Same defensive stance as sync.ts's own localStorage write --
    // storage can throw (Safari's "Block all cookies", sandboxed
    // iframes). Treat that as "no known sync" rather than crash.
    return null;
  }
}

export function OfflineProvider({ children }: { children: ReactNode }) {
  const [isOffline, setIsOffline] = useState(() => !navigator.onLine);
  const [lastSyncedAt, setLastSyncedAt] = useState<string | null>(() =>
    readLastSyncedAt(),
  );

  useEffect(() => {
    function handleOnline() {
      setIsOffline(false);
      // A sync may have completed while this tab was backgrounded/offline
      // (another tab, or this tab's own main.tsx sync firing again on a
      // later load) -- re-read so the banner/auth-restore logic always see
      // the freshest known-good timestamp, not a stale mount-time snapshot.
      setLastSyncedAt(readLastSyncedAt());
    }
    function handleOffline() {
      setIsOffline(true);
      // A sync can complete during this session after the mount-time seed
      // above (main.tsx fires syncVault() on load, in parallel with this
      // provider mounting) without anything else prompting a re-read --
      // the "online" handler above catches that on the *next* reconnect,
      // but without also reading here, going offline for the first time
      // in a session that saw a sync land after mount would show the
      // banner a sync behind the data actually cached.
      setLastSyncedAt(readLastSyncedAt());
    }
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  return (
    <OfflineContext.Provider value={{ isOffline, lastSyncedAt }}>
      {children}
    </OfflineContext.Provider>
  );
}

export function useOffline(): OfflineContextValue {
  const context = useContext(OfflineContext);
  if (!context) {
    throw new Error("useOffline must be used within an OfflineProvider");
  }
  return context;
}

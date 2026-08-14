import { createContext, type ReactNode, useContext, useEffect, useState } from "react";
import { setOnNetworkStatusChange } from "../api/client";
import { LAST_SYNCED_AT_KEY } from "../offline/sync";

interface OfflineContextValue {
  /** True when either the browser reports no network interface at all
   * (`navigator.onLine`, via the `online`/`offline` window events -- KTD6),
   * or the most recent real API request failed at the network layer (see
   * `setOnNetworkStatusChange` in `../api/client`). Both signals are
   * needed: `navigator.onLine` only reflects the OS's network-interface
   * state, not whether *this configured server* is reachable -- verified
   * live against the real desktop app, a docker container going down
   * while the host's wifi stays up left `navigator.onLine` `true` the
   * whole time, so a flag driven by it alone never noticed the server was
   * actually unreachable. A genuine request failure is the more reliable
   * signal for "can I reach my server"; the browser event is kept as a
   * fast, cheap first line for the more obvious fully-offline case. */
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

    // The other half of the signal (see the isOffline doc comment above):
    // a real request's own success/failure, since navigator.onLine alone
    // misses "device online, this specific server unreachable". Reuses
    // the exact same handlers -- a network-layer failure means the same
    // thing here as a browser "offline" event, and a successful request
    // means the same thing as a browser "online" event.
    setOnNetworkStatusChange({ onFailure: handleOffline, onRecovery: handleOnline });

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
      setOnNetworkStatusChange(null);
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

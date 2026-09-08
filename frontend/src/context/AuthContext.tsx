import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  login as loginRequest,
  refreshAccessToken,
  refreshFailureWasAuthRejection,
  setAccessToken,
  setOnRefreshFailure,
} from "../api/client";
import {
  clearSessionEstablished,
  consumeLoggedOut,
  markLoggedOut,
  markSessionEstablished,
  wasSessionEstablished,
} from "../lib/sessionEstablished";
import { syncVault } from "../offline/sync";

// This context deliberately does NOT track `isAdmin`, and only tracks
// `username` when a login form directly supplied it for this session.
//
// The backend's access-token JWT carries only a user id (`sub`) as its
// subject -- no `username`/`is_admin` claim (see the backend's KTD3: a
// claim baked in at login time couldn't be revoked before the token's own
// expiry if an admin were later demoted). There is also no
// `/api/auth/me`-style identity endpoint in this plan. That leaves the
// frontend with no clean way to answer "who is this?" / "are they admin?"
// after a silent refresh-only restore (e.g. a page reload with no fresh
// login form data available) without either decoding unverified claims
// that don't exist, or adding backend scope this unit doesn't justify.
//
// Resolved pragmatically: `isAuthenticated` is the only thing this context
// asserts with confidence. `username` is set only when a login/register
// form on this page load actually knows it; after a reload-triggered
// silent refresh it stays `null` rather than inventing a value.
// `isAdmin` isn't tracked here at all -- `SettingsPage` instead attempts
// `listAccounts()` (admin-only) directly and shows/hides its admin section
// based on whether that call succeeds or 403s, which can't drift out of
// sync with the server's actual authorization state the way a
// client-cached boolean could.
//
// One deliberate exception to "asserts with confidence" (KTD0, broadened):
// when a mount-time refresh attempt fails with anything OTHER than a
// definitive 401/403 from a reachable server -- a network-layer failure, a
// 5xx (backend down behind a live nginx), or the refresh call's own 10s
// timeout -- *and* this browser has a session-established marker in
// `localStorage`, the mount-time restore below treats the session as
// authenticated-from-cache without a real server verdict. This is an
// offline-continuity concession, not a weakening of auth: a reachable
// 401/403 (`refreshFailureWasAuthRejection()` in client.ts -- a response
// came back and said no) is NEVER overridden -- it clears the marker and
// redirects to /login (KTD-A) -- and the next attempt that reaches the
// server runs the completely unmodified refresh flow. `navigator.onLine`
// is used only as a UX shortcut (skip a network attempt known to be
// doomed), never as the accept/reject signal -- it stays `true` for any
// network that can't route to this specific self-hosted server.
interface AuthContextValue {
  isAuthenticated: boolean;
  username: string | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  // KTD-B: a browser with a session on record renders the cached app
  // immediately -- seed `isAuthenticated` true and `loading` false from the
  // marker (read once, lazily), then let the mount effect reconcile against
  // the server in the background. A genuine first-ever visit (no marker)
  // still shows the `Loading...` gate until the mount refresh resolves.
  const [isAuthenticated, setIsAuthenticated] = useState(() => wasSessionEstablished());
  const [username, setUsername] = useState<string | null>(null);
  const [loading, setLoading] = useState(() => !wasSessionEstablished());
  // Guards the mount effect's still-pending refreshAccessToken() promise
  // against an explicit logout() that completes first (review finding #1,
  // 2026-09-07 code review): AuthProvider mounts once for the app's
  // lifetime and never unmounts on logout, so the effect's own `cancelled`
  // closure (set only by its cleanup) is never true at that point --
  // without this, a refresh that resolves after the user clicks Logout
  // would silently re-authenticate the same tab and erase the KTD-C
  // tombstone logout() just wrote, with no reload involved. `logout()` sets
  // this; the mount effect's `.then()` checks it before applying either the
  // success or the cache-restore branch.
  const loggedOutDuringMountRefreshRef = useRef(false);

  useEffect(() => {
    // Restore a session from the refresh-token cookie on mount, when there
    // is no in-memory access token yet (e.g. the tab was just reloaded).
    //
    // Goes through `refreshAccessToken()` (the `navigator.locks`-guarded
    // entry point), not the raw unlocked fetch -- a page reload is exactly
    // when multiple tabs are most likely to hit this concurrently
    // (reopening a window, waking from sleep), and calling the unlocked
    // path here would race the backend's refresh-token rotation directly:
    // the loser looks identical to token theft and the reuse-detection
    // response revokes the whole family, including the winner's
    // freshly-rotated token -- force-logging out every tab.
    let cancelled = false;

    // KTD-C: an explicit `logout()` wrote a one-shot tombstone. Consume it
    // BEFORE any refresh -- clearing the session-established marker alone
    // does not make logout stick, because a successful refresh against the
    // still-valid httpOnly cookie would immediately re-establish the
    // session (the gap the old `logout()` docstring called known).
    if (consumeLoggedOut()) {
      setIsAuthenticated(false);
      setLoading(false);
      return;
    }

    // Read once at mount: nothing between here and the refresh resolving
    // changes it (`login()` is the only writer and cannot run in that
    // window).
    const established = wasSessionEstablished();

    if (!navigator.onLine && established) {
      // Skip the network attempt entirely -- it would just hang until
      // refreshSession()'s 10s timeout with navigator.onLine already known
      // false, staring at "Loading..." for a call known to fail.
      setIsAuthenticated(true);
      setLoading(false);
      return;
    }

    refreshAccessToken()
      .then((token) => {
        if (cancelled || loggedOutDuringMountRefreshRef.current) return;
        if (token !== null) {
          markSessionEstablished();
          setIsAuthenticated(true);
        } else if (established && !refreshFailureWasAuthRejection()) {
          // No server verdict (network failure / 5xx / own timeout) and a
          // session is on record -- authenticated-from-cache. U2's signal
          // has already flipped `OfflineContext.isOffline`, so writes are
          // gated and the offline banner shows.
          setIsAuthenticated(true);
        } else {
          // A definitive 401/403 from a reachable server (KTD-A), or no
          // session on record at all. Clear the marker so a later cold
          // open goes straight to /login via `Loading...` rather than
          // re-seeding and re-flashing the authenticated shell.
          clearSessionEstablished();
          setIsAuthenticated(false);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    // A refresh triggered later by `request()`'s 401-retry path (not this
    // component's own mount-time call above) can also fail. A transient
    // failure (5xx, network) with a session on record keeps the
    // authenticated shell mounted -- forcing `/login` on a brief backend
    // blip would be exactly the "stranded at the login page" behaviour this
    // feature removes. Only a definitive 401/403 (or no marker at all)
    // clears the marker and flips `isAuthenticated` so `RequireAuth`
    // redirects to `/login`.
    setOnRefreshFailure(() => {
      if (wasSessionEstablished() && !refreshFailureWasAuthRejection()) return;
      clearSessionEstablished();
      setIsAuthenticated(false);
    });
    return () => setOnRefreshFailure(null);
  }, []);

  const login = useCallback(async (user: string, password: string) => {
    await loginRequest(user, password);
    markSessionEstablished();
    setIsAuthenticated(true);
    setUsername(user);
    // R1's proactive full-vault sync (main.tsx's own `void syncVault();`)
    // fires exactly once, unconditionally, at page load -- including on
    // the very load that's still showing this login form, before any
    // credentials exist. That call 401s (no access token yet), fails
    // harmlessly per syncVault()'s own docstring, and is never retried for
    // the rest of this page session -- login() doesn't re-trigger it, and
    // nothing else does either. Net effect: logging in and going offline a
    // short while later, with no intervening reload, leaves the vault
    // essentially uncached -- R1's offline snapshot never actually ran.
    // Confirmed live (2026-09-08): 10-20s online after login was not
    // enough for a fresh device to have anything meaningfully cached
    // offline. A page reload while already authenticated doesn't have
    // this gap -- main.tsx's call runs again, and by then a valid
    // refresh-token cookie exists, so its internal 401-retry (through the
    // same `navigator.locks`-guarded refreshAccessToken() this component
    // uses) succeeds. Firing it again here closes the one path that
    // never gets a working attempt.
    void syncVault();
  }, []);

  const logout = useCallback(() => {
    // No server-side logout/session-revoke endpoint exists (only
    // token-specific revoke and account deactivation do). So this clears
    // the in-memory access token and -- KTD-C -- clears the
    // session-established marker and writes a one-shot logout tombstone the
    // mount effect consumes before any refresh. That tombstone is what
    // makes an explicit logout actually stick: the httpOnly refresh-token
    // cookie is unreachable from JS and stays valid server-side, so without
    // it a reload's successful refresh would silently re-establish the
    // session.
    setAccessToken(null);
    clearSessionEstablished();
    markLoggedOut();
    setIsAuthenticated(false);
    setUsername(null);
    // See loggedOutDuringMountRefreshRef's declaration above -- discards a
    // still-pending mount-time refresh's eventual resolution instead of
    // letting it silently re-authenticate this tab.
    loggedOutDuringMountRefreshRef.current = true;
  }, []);

  return (
    <AuthContext.Provider value={{ isAuthenticated, username, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

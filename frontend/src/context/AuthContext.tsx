import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import {
  login as loginRequest,
  refreshAccessToken,
  refreshFailureWasNetworkError,
  setAccessToken,
  setOnRefreshFailure,
} from "../api/client";
import { LAST_SYNCED_AT_KEY } from "../offline/sync";

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
// One deliberate exception to "asserts with confidence" (KTD0): when a
// refresh attempt fails at the network layer (no response ever came back
// -- not an explicit rejection from a reachable server) *and* a previous
// `syncVault()` run has left a last-synced-at marker in `localStorage`,
// the mount-time restore below treats the session as authenticated
// without a real server verdict. This is an offline-continuity
// concession, not a weakening of auth -- an explicit rejection (a
// response that says no) is never overridden by this, only a genuine
// network-layer failure is, and the next attempt that actually reaches
// the server goes through the completely unmodified refresh flow.
interface AuthContextValue {
  isAuthenticated: boolean;
  username: string | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [username, setUsername] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Restore a session from the refresh-token cookie on mount, when there
    // is no in-memory access token yet (e.g. the tab was just reloaded).
    // This is what makes session renewal transparent across a reload, not
    // just across an expired access token within an already-loaded page.
    //
    // Goes through `refreshAccessToken()` (the `navigator.locks`-guarded
    // entry point), not the raw unlocked fetch -- a page reload is exactly
    // when multiple tabs are most likely to hit this concurrently
    // (reopening a window, waking from sleep), and calling the unlocked
    // path here would race the backend's refresh-token rotation directly:
    // the loser looks identical to token theft and the reuse-detection
    // response revokes the whole family, including the winner's
    // freshly-rotated token -- force-logging out every tab.
    // KTD0: offline-aware restore. A previously synced vault existing in
    // `localStorage` is evidence a session was valid as of that sync, so
    // a *network-layer* refresh failure (see `refreshFailureWasNetworkError`
    // in client.ts -- the fetch itself never got a response, as opposed to
    // an explicit rejection from a server that was actually reached) is
    // treated as offline continuity rather than a logout.
    //
    // Deliberately NOT gated on `navigator.onLine` for that decision:
    // `navigator.onLine` only reliably reports `false` for a genuinely
    // absent network interface (airplane mode). It stays `true` the
    // moment *any* network is up, even one that can't reach this specific
    // self-hosted server -- coffee-shop wifi, a different LAN, mobile
    // data with no route home. That's the overwhelmingly common way this
    // app actually goes "offline" from the user's perspective, and a
    // `navigator.onLine`-gated check would silently fail to cover it,
    // logging the user out instead of restoring the offline snapshot.
    // `navigator.onLine` is still useful as a pure UX shortcut below --
    // skip the doomed network attempt outright when we're sure there's no
    // network at all -- but the actual accept/reject decision after a
    // real attempt is made rests on what that attempt discovered, not on
    // the browser's optimistic guess.
    //
    // This never bypasses a *reachable* server's actual verdict: an
    // explicit rejection (a response came back and said no) still logs
    // the user out even with a snapshot present -- only a network-layer
    // failure falls back to offline-valid. The moment the network
    // genuinely reaches the server again, the very next mount or
    // 401-retry runs the unmodified refresh flow and would correctly log
    // out an actually-invalid session.
    let cancelled = false;

    function hasSyncedSnapshot(): boolean {
      return localStorage.getItem(LAST_SYNCED_AT_KEY) !== null;
    }

    if (!navigator.onLine && hasSyncedSnapshot()) {
      // Skip the network attempt entirely -- it would just hang until
      // refreshSession()'s 10s timeout with navigator.onLine already
      // known false, staring at "Loading..." for a call known to fail.
      setIsAuthenticated(true);
      setLoading(false);
      return;
    }

    refreshAccessToken()
      .then((token) => {
        if (cancelled) return;
        if (token !== null) {
          setIsAuthenticated(true);
        } else if (refreshFailureWasNetworkError() && hasSyncedSnapshot()) {
          setIsAuthenticated(true);
        } else {
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
    // component's own mount-time call above) can also fail -- e.g. the
    // refresh cookie itself expired or the account was deactivated mid-
    // session. Without this, the authenticated shell stayed mounted with
    // every subsequent API call throwing, instead of redirecting to
    // `/login` the same way an unauthenticated visit does.
    setOnRefreshFailure(() => setIsAuthenticated(false));
    return () => setOnRefreshFailure(null);
  }, []);

  const login = useCallback(async (user: string, password: string) => {
    await loginRequest(user, password);
    setIsAuthenticated(true);
    setUsername(user);
  }, []);

  const logout = useCallback(() => {
    // No server-side logout/session-revoke endpoint exists in this plan
    // (only token-specific revoke and account deactivation do), so this
    // can only clear the in-memory access token -- the httpOnly
    // refresh-token cookie is unreachable from JS and stays valid
    // server-side, meaning a page reload right after "logout" would
    // silently re-establish the session via that cookie. A genuine, known
    // gap given the backend surface available to this unit.
    setAccessToken(null);
    setIsAuthenticated(false);
    setUsername(null);
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

import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { login as loginRequest, refreshSession, setAccessToken } from "../api/client";

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
    let cancelled = false;
    refreshSession()
      .then((token) => {
        if (cancelled) return;
        setAccessToken(token);
        setIsAuthenticated(true);
      })
      .catch(() => {
        if (cancelled) return;
        setAccessToken(null);
        setIsAuthenticated(false);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
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

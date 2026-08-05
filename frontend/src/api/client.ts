import type {
  AccountSummary,
  ApiTokenMeta,
  CreateApiTokenResult,
  CreateInviteResult,
} from "../types/auth";
import type { GraphResponse, Note, NoteMeta } from "../types/note";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

// The access token lives in memory only -- never localStorage/sessionStorage
// (this codebase has zero prior localStorage usage). An in-memory store is
// more XSS-resistant than persisting a JWT to disk; the trade-off is that it
// doesn't survive a page reload on its own -- AuthContext's silent refresh
// on mount (via the httpOnly refresh-token cookie) is what restores a
// session across a reload.
let accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

// The two endpoints that must never trigger a refresh-and-retry on 401:
// `/auth/login` (a failed login is a real 401 the caller needs to see, not
// something a token refresh could ever fix) and `/auth/refresh` itself
// (retrying a failed refresh with another refresh would loop forever).
function isAuthBootstrapPath(path: string): boolean {
  return path === "/auth/login" || path === "/auth/refresh";
}

async function fetchWithToken(
  path: string,
  init: RequestInit | undefined,
  token: string | null,
): Promise<Response> {
  const headers = new Headers(init?.headers);
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  return fetch(`${API_BASE}/api${path}`, {
    ...init,
    headers,
    // Needed so the httpOnly refresh-token cookie is sent to
    // `/api/auth/refresh` -- harmless on every other request since they
    // don't read cookies at all.
    credentials: "include",
  });
}

async function toResult<T>(
  response: Response,
  path: string,
  init?: RequestInit,
): Promise<T> {
  if (!response.ok) {
    throw new Error(`${init?.method ?? "GET"} ${path} failed: ${response.status}`);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response = await fetchWithToken(path, init, accessToken);

  if (response.status === 401 && !isAuthBootstrapPath(path)) {
    const refreshedToken = await refreshAccessToken();
    if (refreshedToken) {
      response = await fetchWithToken(path, init, refreshedToken);
    }
    // On refresh failure `refreshAccessToken()` has already cleared the
    // access token; `response` here is still the original 401, which
    // `toResult()` below turns into a thrown error -- no second retry, no
    // navigation (this module has no router access; `AuthContext` is
    // responsible for redirecting to /login once it observes this).
  }

  return toResult<T>(response, path, init);
}

// The actual `/api/auth/refresh` POST call, factored out from
// `refreshAccessToken()`'s locking/dedup logic below so that logic isn't
// duplicated fetch plumbing `request()` already provides. Deliberately NOT
// built on `request()`/`fetchWithToken()`: this call must never send an
// `Authorization` header, even if `accessToken` happens to be stale or set
// -- refresh authenticates via the httpOnly cookie only, and a stray bearer
// token here would be misleading to anyone reading this code later.
export async function refreshSession(): Promise<string> {
  const response = await fetch(`${API_BASE}/api/auth/refresh`, {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok) {
    throw new Error(`POST /auth/refresh failed: ${response.status}`);
  }
  const data = (await response.json()) as { access_token: string };
  return data.access_token;
}

async function performRefresh(): Promise<string | null> {
  try {
    const token = await refreshSession();
    setAccessToken(token);
    return token;
  } catch {
    setAccessToken(null);
    return null;
  }
}

// Cross-tab single-flight guard: the refresh-token cookie is shared
// browser-wide, so two tabs racing to refresh at the same moment would
// otherwise both call `/api/auth/refresh` -- the second one would look
// identical to token-theft (an already-rotated refresh token being reused)
// and get rejected, force-logging out a legitimate session.
// `navigator.locks.request()` serializes this not just within one tab's
// in-page state but across every open tab of the same origin.
async function refreshAccessToken(): Promise<string | null> {
  const tokenBeforeRefresh = accessToken;

  return navigator.locks.request("auth-refresh", async () => {
    // Another tab (or another caller in this tab) may have already won
    // the lock race and refreshed by the time we get in here -- if the
    // in-memory token moved on from what we saw before requesting the
    // lock, use that instead of hitting `/auth/refresh` again.
    if (accessToken !== tokenBeforeRefresh) {
      return accessToken;
    }
    return performRefresh();
  });
}

export function encodeNotePath(path: string): string {
  return path.split("/").map(encodeURIComponent).join("/");
}

export function listNotes(): Promise<NoteMeta[]> {
  return request<NoteMeta[]>("/notes");
}

export function getNote(path: string): Promise<Note> {
  return request<Note>(`/notes/${encodeNotePath(path)}`);
}

export function putNote(path: string, content: string): Promise<Note> {
  return request<Note>(`/notes/${encodeNotePath(path)}`, {
    method: "PUT",
    headers: { "Content-Type": "text/markdown" },
    body: content,
  });
}

export function deleteNote(path: string): Promise<void> {
  return request<void>(`/notes/${encodeNotePath(path)}`, { method: "DELETE" });
}

export function moveNote(path: string, newPath: string, title?: string): Promise<Note> {
  return request<Note>(`/notes/${encodeNotePath(path)}/move`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ new_path: newPath, title: title ?? null }),
  });
}

export function getGraph(): Promise<GraphResponse> {
  return request<GraphResponse>("/graph");
}

export function getBacklinks(path: string): Promise<NoteMeta[]> {
  return request<NoteMeta[]>(`/notes/${encodeNotePath(path)}/backlinks`);
}

export function searchNotes(query: string): Promise<NoteMeta[]> {
  return request<NoteMeta[]>(`/search?q=${encodeURIComponent(query)}`);
}

// --- Auth ---

export async function login(username: string, password: string): Promise<void> {
  const data = await request<{ access_token: string }>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  setAccessToken(data.access_token);
}

export function register(
  username: string,
  password: string,
  token: string,
): Promise<void> {
  return request<void>("/auth/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password, token }),
  });
}

// --- Personal API tokens ---

export function createApiToken(name: string): Promise<CreateApiTokenResult> {
  return request<CreateApiTokenResult>("/tokens", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

export function listApiTokens(): Promise<ApiTokenMeta[]> {
  return request<ApiTokenMeta[]>("/tokens");
}

export function revokeApiToken(id: number): Promise<void> {
  return request<void>(`/tokens/${id}`, { method: "DELETE" });
}

// --- Admin ---

export function createInvite(): Promise<CreateInviteResult> {
  return request<CreateInviteResult>("/invites", { method: "POST" });
}

export function listAccounts(): Promise<AccountSummary[]> {
  return request<AccountSummary[]>("/accounts");
}

export function deactivateAccount(id: number): Promise<void> {
  return request<void>(`/accounts/${id}/deactivate`, { method: "POST" });
}

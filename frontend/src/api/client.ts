import type {
  AccountSummary,
  ApiTokenMeta,
  CreateApiTokenResult,
  CreateInviteResult,
  LoginResponse,
} from "../types/auth";
import type {
  AttachmentUploadResult,
  GraphResponse,
  Note,
  NoteMeta,
  TaskItem,
} from "../types/note";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

// Every `catch (err: unknown)` block in this app that displays a caught
// error to the user should read `err.message` through this, not
// `String(err)` -- `Error.prototype.toString()` (what `String()` calls)
// prepends the error's `name` (e.g. "ApiError: Invalid registration
// token"), which is exactly the kind of technical noise a user-facing
// error message shouldn't carry.
export function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

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

// Lets `AuthContext` learn when a *post-mount* refresh attempt (triggered
// by `request()`'s 401-retry path below, not the initial mount-time one it
// drives directly) definitively fails, so it can flip `isAuthenticated` to
// `false` and let `RequireAuth` redirect to `/login` -- without this, a
// session that dies mid-use left the authenticated shell mounted with
// every subsequent call throwing, instead of a clean redirect. A plain
// module-level callback, not an event system: this client has exactly one
// consumer (`AuthContext`) and no need for multiple subscribers.
let onRefreshFailure: (() => void) | null = null;

export function setOnRefreshFailure(callback: (() => void) | null): void {
  onRefreshFailure = callback;
}

// Lets `OfflineContext` learn when a live request genuinely fails at the
// network layer (`fetch()` itself never got a response), vs. succeeding
// (even with a non-2xx status -- that still proves the network reached the
// server). `navigator.onLine` only reliably reports the OS's network-
// interface state, not whether *this* configured server is reachable --
// verified live against the real desktop app: a docker container going
// down while the host machine's wifi stays up leaves `navigator.onLine`
// `true` the whole time, so a banner driven by it alone never appears even
// though the user is silently viewing a stale cached snapshot (exactly the
// scenario R5 exists to surface). Plain module-level callbacks, mirroring
// `onRefreshFailure` above: one consumer, no need for an event system.
let onNetworkFailure: (() => void) | null = null;
let onNetworkRecovery: (() => void) | null = null;

export function setOnNetworkStatusChange(
  callbacks: { onFailure: () => void; onRecovery: () => void } | null,
): void {
  onNetworkFailure = callbacks?.onFailure ?? null;
  onNetworkRecovery = callbacks?.onRecovery ?? null;
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
  try {
    const response = await fetch(`${API_BASE}/api${path}`, {
      ...init,
      headers,
      // Needed so the httpOnly refresh-token cookie is sent to
      // `/api/auth/refresh` -- harmless on every other request since they
      // don't read cookies at all.
      credentials: "include",
    });
    // A response -- any response, including a non-2xx one -- proves the
    // network layer actually reached the server. Only fetch() itself
    // throwing (below) means it didn't.
    onNetworkRecovery?.();
    return response;
  } catch (err) {
    onNetworkFailure?.();
    throw err;
  }
}

// Thrown instead of a plain `Error` on any non-2xx response, so callers
// that need the status code (e.g. distinguishing a validation failure
// from an auth failure) don't have to string-match the message -- see
// `LoginPage.tsx`, which used to check `String(err).includes("401")`
// before this existed.
export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

// Every backend error response is FastAPI's default `{"detail": "..."}`
// shape (confirmed across every route in this codebase) -- and that
// `detail` text is already the right, specific, user-facing message
// (e.g. "password must be at least 12 characters", "Invalid registration
// token"). Discarding it in favor of a generic "POST /path failed: 400"
// forced every form on this page to show a useless error no matter what
// actually went wrong. Falls back to the generic message only when the
// body isn't the expected shape (a network-level failure, a non-JSON
// response, or a future endpoint that doesn't follow the convention).
async function readErrorDetail(response: Response): Promise<string | null> {
  try {
    const body: unknown = await response.clone().json();
    if (
      body !== null &&
      typeof body === "object" &&
      "detail" in body &&
      typeof body.detail === "string"
    ) {
      return body.detail;
    }
  } catch {
    // Not JSON (or no body at all) -- fall through to the generic message.
  }
  return null;
}

async function toResult<T>(
  response: Response,
  path: string,
  init?: RequestInit,
): Promise<T> {
  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new ApiError(
      detail ?? `${init?.method ?? "GET"} ${path} failed: ${response.status}`,
      response.status,
    );
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

// The shared 401-detect-refresh-retry logic, factored out from `request()`
// so `fetchAttachmentBlobUrl()` below can reuse it without either calling
// bare `fetchWithToken()` (which has no retry -- a stale access token would
// just fail) or duplicating this retry logic ad-hoc (two copies of "detect
// 401, refresh, retry once" drifting apart over time). Returns the raw
// `Response`; each caller does its own response-to-value conversion
// (`toResult()`'s JSON parsing here, blob reading in the attachments case).
async function fetchWithRetry(path: string, init?: RequestInit): Promise<Response> {
  let response = await fetchWithToken(path, init, accessToken);

  if (response.status === 401 && !isAuthBootstrapPath(path)) {
    const refreshedToken = await refreshAccessToken();
    if (refreshedToken) {
      response = await fetchWithToken(path, init, refreshedToken);
    }
    // On refresh failure `refreshAccessToken()` has already cleared the
    // access token; `response` here is still the original 401, which the
    // caller's response handling below turns into a thrown error -- no
    // second retry, no navigation (this module has no router access;
    // `AuthContext` is responsible for redirecting to /login once it
    // observes this).
  }

  return response;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetchWithRetry(path, init);
  return toResult<T>(response, path, init);
}

// How long a single `/api/auth/refresh` attempt gets before it's treated
// as failed. Without this, a hung network call would never resolve --
// and since this fetch runs inside the `navigator.locks` critical section
// below, a hang here blocks every tab's refresh indefinitely, which in
// turn leaves `AuthContext`'s mount-time `loading` flag stuck `true`
// forever (its `.finally()` never fires).
const REFRESH_TIMEOUT_MS = 10_000;

// The actual `/api/auth/refresh` POST call, factored out from
// `refreshAccessToken()`'s locking/dedup logic below so that logic isn't
// duplicated fetch plumbing `request()` already provides. Deliberately NOT
// built on `request()`/`fetchWithToken()`: this call must never send an
// `Authorization` header, even if `accessToken` happens to be stale or set
// -- refresh authenticates via the httpOnly cookie only, and a stray bearer
// token here would be misleading to anyone reading this code later. Not
// exported: every caller, in-tab or cross-tab, must go through the
// `navigator.locks`-guarded `refreshAccessToken()` below, never this raw
// fetch directly -- see that function's docstring for why.
// Set by refreshSession() below, distinguishing a network-layer failure
// (the fetch itself never got a response back -- DNS failure, connection
// refused, this call's own timeout aborting it) from an explicit HTTP
// rejection (a response DID come back, e.g. a 401 -- the server was
// reached and said no). AuthContext's offline-restore fallback (KTD0)
// needs exactly this distinction: a network failure with a previously
// synced snapshot is offline continuity; an explicit rejection must still
// log the user out even when a snapshot exists, or a genuinely revoked
// session would never actually get logged out while a stale snapshot sits
// in localStorage. Module-scoped rather than thrown/returned from
// refreshSession() to avoid changing that function's or performRefresh()'s
// external contract for their other callers.
let lastRefreshFailureWasNetworkError = false;

export function refreshFailureWasNetworkError(): boolean {
  return lastRefreshFailureWasNetworkError;
}

async function refreshSession(): Promise<string> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REFRESH_TIMEOUT_MS);
  let response: Response;
  try {
    try {
      response = await fetch(`${API_BASE}/api/auth/refresh`, {
        method: "POST",
        credentials: "include",
        signal: controller.signal,
      });
    } catch (err) {
      // fetch() itself rejected -- no HTTP response was ever received.
      // Never a real server verdict, regardless of the underlying cause.
      lastRefreshFailureWasNetworkError = true;
      onNetworkFailure?.();
      throw err;
    }
    // A response -- any response -- proves the network layer reached the
    // server, same reasoning as fetchWithToken() above.
    onNetworkRecovery?.();
    if (!response.ok) {
      // A response came back and the server said no -- an explicit
      // rejection, not a network failure.
      lastRefreshFailureWasNetworkError = false;
      throw new Error(`POST /auth/refresh failed: ${response.status}`);
    }
    lastRefreshFailureWasNetworkError = false;
    const data = (await response.json()) as LoginResponse;
    return data.access_token;
  } finally {
    window.clearTimeout(timeout);
  }
}

async function performRefresh(): Promise<string | null> {
  try {
    const token = await refreshSession();
    setAccessToken(token);
    return token;
  } catch {
    setAccessToken(null);
    onRefreshFailure?.();
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
//
// Exported and the ONLY entry point into refreshing a session -- this
// includes `AuthContext`'s mount-time silent-refresh attempt (restoring a
// session on page reload), which is exactly the moment several tabs are
// most likely to hit this concurrently (reopening a window, waking from
// sleep). Calling the raw `refreshSession()` from there instead would
// skip this guard entirely and reintroduce the false-positive-theft race
// this function exists to prevent.
export async function refreshAccessToken(): Promise<string | null> {
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

export function getTasks(): Promise<TaskItem[]> {
  return request<TaskItem[]>("/tasks");
}

export function getBacklinks(path: string): Promise<NoteMeta[]> {
  return request<NoteMeta[]>(`/notes/${encodeNotePath(path)}/backlinks`);
}

export function searchNotes(query: string): Promise<NoteMeta[]> {
  return request<NoteMeta[]>(`/search?q=${encodeURIComponent(query)}`);
}

// Uploads raw image bytes (not `FormData`/multipart) matching the backend's
// `POST /api/attachments` contract, which reads the request body directly
// and infers the image type from `Content-Type`. Built on `request()`
// rather than a bespoke `fetch()` call so a paste that races an expired
// access token still gets the same 401-refresh-and-retry handling every
// other authenticated call gets, instead of silently failing.
export function uploadAttachment(
  notePath: string,
  file: File,
): Promise<AttachmentUploadResult> {
  return request<AttachmentUploadResult>(
    `/attachments?note_path=${encodeURIComponent(notePath)}`,
    {
      method: "POST",
      headers: { "Content-Type": file.type },
      body: file,
    },
  );
}

// Fetches an attachment's raw image bytes through `GET
// /api/attachments/{path}` and returns an object URL for the resulting
// blob, so `<img>` tags can reference it without embedding the access
// token in a URL (which `<img src>` can't attach an `Authorization` header
// to anyway, and a URL-embedded token would leak into browser history/
// logs). Built on `fetchWithRetry()` -- not `request()` -- because
// `request()`/`toResult()` always parses the response as JSON; image bytes
// need `response.blob()` instead. Still throws the same `ApiError` shape as
// `request()` on a non-2xx response so callers can `.catch()` it the same
// way as everywhere else in this codebase. Callers are responsible for
// `URL.revokeObjectURL()`-ing the result once it's no longer displayed.
export async function fetchAttachmentBlobUrl(attachmentPath: string): Promise<string> {
  const path = `/attachments/${encodeNotePath(attachmentPath)}`;
  const response = await fetchWithRetry(path);

  if (!response.ok) {
    const detail = await readErrorDetail(response);
    throw new ApiError(
      detail ?? `GET ${path} failed: ${response.status}`,
      response.status,
    );
  }

  const blob = await response.blob();
  return URL.createObjectURL(blob);
}

// --- Auth ---

export async function login(username: string, password: string): Promise<void> {
  const data = await request<LoginResponse>("/auth/login", {
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

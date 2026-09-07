import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Mocked in place of the real API client so tests control exactly when/how
// login and refresh resolve, without touching the network. Typed explicitly
// per this project's convention -- an untyped `vi.fn()` infers a zero-arg
// signature that `tsc -b` then rejects when the mock is called with args.
const mockLogin = vi.fn<(username: string, password: string) => Promise<void>>();
const mockRefreshAccessToken = vi.fn<() => Promise<string | null>>();
const mockSetAccessToken = vi.fn<(token: string | null) => void>();
// Defaults to `false` (not a definitive auth rejection) -- the offline-
// continuity default. A test that wants "the session really is dead" sets
// this to `true`.
const mockRefreshFailureWasAuthRejection = vi.fn<() => boolean>(() => false);
let capturedRefreshFailureCallback: (() => void) | null = null;
const mockSetOnRefreshFailure = vi.fn<(callback: (() => void) | null) => void>(
  (callback) => {
    capturedRefreshFailureCallback = callback;
  },
);

vi.mock("../api/client", () => ({
  login: (username: string, password: string) => mockLogin(username, password),
  refreshAccessToken: () => mockRefreshAccessToken(),
  refreshFailureWasAuthRejection: () => mockRefreshFailureWasAuthRejection(),
  setAccessToken: (token: string | null) => mockSetAccessToken(token),
  setOnRefreshFailure: (callback: (() => void) | null) =>
    mockSetOnRefreshFailure(callback),
}));

// The session-established marker + logout tombstone are mocked so tests can
// drive `wasSessionEstablished()` / `consumeLoggedOut()` directly and assert
// on the mark/clear calls, without depending on jsdom's localStorage.
const mockWasSessionEstablished = vi.fn<() => boolean>(() => false);
const mockConsumeLoggedOut = vi.fn<() => boolean>(() => false);
const mockMarkSessionEstablished = vi.fn<() => void>();
const mockClearSessionEstablished = vi.fn<() => void>();
const mockMarkLoggedOut = vi.fn<() => void>();

vi.mock("../lib/sessionEstablished", () => ({
  wasSessionEstablished: () => mockWasSessionEstablished(),
  consumeLoggedOut: () => mockConsumeLoggedOut(),
  markSessionEstablished: () => mockMarkSessionEstablished(),
  clearSessionEstablished: () => mockClearSessionEstablished(),
  markLoggedOut: () => mockMarkLoggedOut(),
}));

import { setNavigatorOnLine } from "../test/factories";
import { AuthProvider, useAuth } from "./AuthContext";

// Renders the context's live values as text so tests can assert on
// post-update state via RTL queries, and exposes login/logout as buttons so
// the test can trigger them the same way real consumers would.
function Consumer() {
  const { isAuthenticated, username, loading, login, logout } = useAuth();
  return (
    <div>
      <div data-testid="loading">{String(loading)}</div>
      <div data-testid="isAuthenticated">{String(isAuthenticated)}</div>
      <div data-testid="username">{username ?? "null"}</div>
      <button type="button" onClick={() => void login("alice", "hunter2")}>
        login
      </button>
      <button type="button" onClick={() => logout()}>
        logout
      </button>
    </div>
  );
}

beforeEach(() => {
  mockLogin.mockReset();
  mockRefreshAccessToken.mockReset();
  mockSetAccessToken.mockReset();
  mockRefreshFailureWasAuthRejection.mockReset();
  mockRefreshFailureWasAuthRejection.mockReturnValue(false);
  mockSetOnRefreshFailure.mockReset();
  mockSetOnRefreshFailure.mockImplementation((callback) => {
    capturedRefreshFailureCallback = callback;
  });
  capturedRefreshFailureCallback = null;
  mockWasSessionEstablished.mockReset();
  mockWasSessionEstablished.mockReturnValue(false);
  mockConsumeLoggedOut.mockReset();
  mockConsumeLoggedOut.mockReturnValue(false);
  mockMarkSessionEstablished.mockReset();
  mockClearSessionEstablished.mockReset();
  mockMarkLoggedOut.mockReset();
  setNavigatorOnLine(true);
});

afterEach(() => {
  setNavigatorOnLine(true);
});

describe("AuthProvider mount restore", () => {
  it("restores an authenticated session when refresh resolves a token, and marks the browser established", async () => {
    mockRefreshAccessToken.mockResolvedValue("access-token");

    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("loading")).toHaveTextContent("false"),
    );
    expect(screen.getByTestId("isAuthenticated")).toHaveTextContent("true");
    expect(mockMarkSessionEstablished).toHaveBeenCalled();
  });

  it("leaves the session unauthenticated when refresh resolves null and no session is on record", async () => {
    mockRefreshAccessToken.mockResolvedValue(null);

    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("loading")).toHaveTextContent("false"),
    );
    expect(screen.getByTestId("isAuthenticated")).toHaveTextContent("false");
  });

  it("restores from cache when refresh fails without an auth rejection (5xx / timeout / network) and a session is on record", async () => {
    mockWasSessionEstablished.mockReturnValue(true);
    mockRefreshAccessToken.mockResolvedValue(null);
    mockRefreshFailureWasAuthRejection.mockReturnValue(false);

    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("loading")).toHaveTextContent("false"),
    );
    expect(screen.getByTestId("isAuthenticated")).toHaveTextContent("true");
    expect(mockRefreshAccessToken).toHaveBeenCalled();
  });

  it("logs out and clears the marker on a definitive 401/403, even with a session on record", async () => {
    mockWasSessionEstablished.mockReturnValue(true);
    mockRefreshAccessToken.mockResolvedValue(null);
    mockRefreshFailureWasAuthRejection.mockReturnValue(true);

    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("loading")).toHaveTextContent("false"),
    );
    expect(screen.getByTestId("isAuthenticated")).toHaveTextContent("false");
    expect(mockClearSessionEstablished).toHaveBeenCalled();
  });

  it("consumes a logout tombstone before any refresh -- straight to unauthenticated", async () => {
    mockConsumeLoggedOut.mockReturnValue(true);
    mockWasSessionEstablished.mockReturnValue(true);

    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("loading")).toHaveTextContent("false"),
    );
    expect(screen.getByTestId("isAuthenticated")).toHaveTextContent("false");
    expect(mockRefreshAccessToken).not.toHaveBeenCalled();
  });

  it("restores from cache when offline with a session on record, without calling refreshAccessToken", async () => {
    setNavigatorOnLine(false);
    mockWasSessionEstablished.mockReturnValue(true);

    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("loading")).toHaveTextContent("false"),
    );
    expect(screen.getByTestId("isAuthenticated")).toHaveTextContent("true");
    expect(mockRefreshAccessToken).not.toHaveBeenCalled();
  });

  it("leaves the session unauthenticated when offline with no session on record", async () => {
    setNavigatorOnLine(false);
    mockWasSessionEstablished.mockReturnValue(false);
    mockRefreshAccessToken.mockResolvedValue(null);

    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("loading")).toHaveTextContent("false"),
    );
    expect(screen.getByTestId("isAuthenticated")).toHaveTextContent("false");
  });

  it("seeds isAuthenticated true and loading false synchronously when a session is on record (KTD-B)", () => {
    mockWasSessionEstablished.mockReturnValue(true);
    // A never-resolving refresh: the seed must not depend on it settling.
    mockRefreshAccessToken.mockReturnValue(new Promise(() => {}));

    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    );

    // Asserted synchronously, before any `await` -- the optimistic seed.
    expect(screen.getByTestId("loading")).toHaveTextContent("false");
    expect(screen.getByTestId("isAuthenticated")).toHaveTextContent("true");
  });
});

describe("AuthProvider mid-session refresh failure", () => {
  it("keeps the shell mounted on a transient failure (no auth rejection) with a session on record", async () => {
    mockWasSessionEstablished.mockReturnValue(true);
    mockRefreshAccessToken.mockResolvedValue("access-token");
    mockRefreshFailureWasAuthRejection.mockReturnValue(false);

    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("loading")).toHaveTextContent("false"),
    );
    expect(screen.getByTestId("isAuthenticated")).toHaveTextContent("true");

    act(() => {
      capturedRefreshFailureCallback?.();
    });

    expect(screen.getByTestId("isAuthenticated")).toHaveTextContent("true");
    expect(mockClearSessionEstablished).not.toHaveBeenCalled();
  });

  it("logs out and clears the marker on a definitive 401/403 mid-session", async () => {
    mockWasSessionEstablished.mockReturnValue(true);
    mockRefreshAccessToken.mockResolvedValue("access-token");

    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("loading")).toHaveTextContent("false"),
    );

    mockRefreshFailureWasAuthRejection.mockReturnValue(true);
    act(() => {
      capturedRefreshFailureCallback?.();
    });

    expect(screen.getByTestId("isAuthenticated")).toHaveTextContent("false");
    expect(mockClearSessionEstablished).toHaveBeenCalled();
  });
});

describe("AuthProvider login / logout", () => {
  it("sets isAuthenticated, username, and the established marker on successful login", async () => {
    mockRefreshAccessToken.mockResolvedValue(null);
    mockLogin.mockResolvedValue(undefined);
    const user = userEvent.setup();

    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("loading")).toHaveTextContent("false"),
    );

    await user.click(screen.getByRole("button", { name: "login" }));

    await waitFor(() =>
      expect(screen.getByTestId("isAuthenticated")).toHaveTextContent("true"),
    );
    expect(screen.getByTestId("username")).toHaveTextContent("alice");
    expect(mockLogin).toHaveBeenCalledWith("alice", "hunter2");
    expect(mockMarkSessionEstablished).toHaveBeenCalled();
  });

  it("clears auth state, the access token, the marker, and drops a logout tombstone on logout", async () => {
    mockRefreshAccessToken.mockResolvedValue(null);
    mockLogin.mockResolvedValue(undefined);
    const user = userEvent.setup();

    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("loading")).toHaveTextContent("false"),
    );

    await user.click(screen.getByRole("button", { name: "login" }));
    await waitFor(() =>
      expect(screen.getByTestId("isAuthenticated")).toHaveTextContent("true"),
    );

    await user.click(screen.getByRole("button", { name: "logout" }));

    await waitFor(() =>
      expect(screen.getByTestId("isAuthenticated")).toHaveTextContent("false"),
    );
    expect(screen.getByTestId("username")).toHaveTextContent("null");
    expect(mockSetAccessToken).toHaveBeenCalledWith(null);
    expect(mockClearSessionEstablished).toHaveBeenCalled();
    expect(mockMarkLoggedOut).toHaveBeenCalled();
  });

  // Regression coverage for review finding #1 (2026-09-07 code review):
  // AuthProvider mounts once for the app's lifetime and never unmounts on
  // logout, so the mount effect's own `cancelled` closure (set only by its
  // cleanup) is never true here -- without a separate guard, a refresh that
  // resolves *after* an explicit logout would silently re-authenticate the
  // same tab and erase the just-written logout tombstone, no reload
  // involved.
  it("discards a mount-time refresh that resolves after an explicit logout, even when it would have succeeded", async () => {
    mockWasSessionEstablished.mockReturnValue(true);
    let resolveRefresh!: (token: string | null) => void;
    mockRefreshAccessToken.mockReturnValue(
      new Promise((resolve) => {
        resolveRefresh = resolve;
      }),
    );
    const user = userEvent.setup();

    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    );
    // The mount refresh is still pending -- optimistic seed (KTD-B) already
    // shows the shell as authenticated at this point.
    expect(screen.getByTestId("isAuthenticated")).toHaveTextContent("true");

    await user.click(screen.getByRole("button", { name: "logout" }));
    await waitFor(() =>
      expect(screen.getByTestId("isAuthenticated")).toHaveTextContent("false"),
    );
    mockMarkSessionEstablished.mockClear();

    // The mount-time refresh resolves only now, with a real token -- the
    // exact race the fix guards against.
    await act(async () => {
      resolveRefresh("access-token");
      await Promise.resolve();
    });

    expect(screen.getByTestId("isAuthenticated")).toHaveTextContent("false");
    expect(mockMarkSessionEstablished).not.toHaveBeenCalled();
  });

  it("throws when useAuth is called outside an AuthProvider", () => {
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() => render(<Consumer />)).toThrow(
      "useAuth must be used within an AuthProvider",
    );

    consoleErrorSpy.mockRestore();
  });
});

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
// Defaults to `false` (an explicit rejection, not a network failure) --
// the safer default, since a test that forgets to set this should exercise
// "the session really is logged out", not silently fall into the
// offline-restore path it isn't testing for.
const mockRefreshFailureWasNetworkError = vi.fn<() => boolean>(() => false);
let capturedRefreshFailureCallback: (() => void) | null = null;
const mockSetOnRefreshFailure = vi.fn<(callback: (() => void) | null) => void>(
  (callback) => {
    capturedRefreshFailureCallback = callback;
  },
);

vi.mock("../api/client", () => ({
  login: (username: string, password: string) => mockLogin(username, password),
  refreshAccessToken: () => mockRefreshAccessToken(),
  refreshFailureWasNetworkError: () => mockRefreshFailureWasNetworkError(),
  setAccessToken: (token: string | null) => mockSetAccessToken(token),
  setOnRefreshFailure: (callback: (() => void) | null) =>
    mockSetOnRefreshFailure(callback),
}));

import { LAST_SYNCED_AT_KEY } from "../offline/sync";
import { AuthProvider, useAuth } from "./AuthContext";

function setNavigatorOnLine(value: boolean) {
  Object.defineProperty(window.navigator, "onLine", {
    configurable: true,
    value,
  });
}

// Renders the context's live values as text/data attributes so tests can
// assert on post-update state via RTL queries, and exposes login/logout as
// buttons so the test can trigger them the same way real consumers would.
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
  mockRefreshFailureWasNetworkError.mockReset();
  mockRefreshFailureWasNetworkError.mockReturnValue(false);
  mockSetOnRefreshFailure.mockReset();
  mockSetOnRefreshFailure.mockImplementation((callback) => {
    capturedRefreshFailureCallback = callback;
  });
  capturedRefreshFailureCallback = null;
  window.localStorage.clear();
  setNavigatorOnLine(true);
});

afterEach(() => {
  setNavigatorOnLine(true);
});

describe("AuthProvider", () => {
  it("restores an authenticated session on mount when refresh resolves a token", async () => {
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
  });

  it("leaves the session unauthenticated on mount when refresh resolves null", async () => {
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

  it("sets isAuthenticated and username on successful login", async () => {
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
  });

  it("clears auth state and the access token on logout", async () => {
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
  });

  it("flips isAuthenticated to false when the registered refresh-failure callback fires", async () => {
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

    expect(capturedRefreshFailureCallback).not.toBeNull();
    act(() => {
      capturedRefreshFailureCallback?.();
    });

    expect(screen.getByTestId("isAuthenticated")).toHaveTextContent("false");
  });

  it("restores an authenticated session on mount when offline with a prior synced-at marker, without calling refreshAccessToken", async () => {
    setNavigatorOnLine(false);
    window.localStorage.setItem(LAST_SYNCED_AT_KEY, "2026-08-10T12:00:00.000Z");

    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("loading")).toHaveTextContent("false"),
    );
    expect(screen.getByTestId("isAuthenticated")).toHaveTextContent("true");
    // The whole point of the offline-restore short-circuit is skipping the
    // network attempt entirely -- not just tolerating its eventual
    // failure -- so refreshAccessToken must never be reached.
    expect(mockRefreshAccessToken).not.toHaveBeenCalled();
  });

  it("leaves the session unauthenticated when offline with no prior synced-at marker", async () => {
    setNavigatorOnLine(false);
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

  it("restores an authenticated session when refresh fails at the network layer while navigator.onLine still reports true, with a synced-at marker present", async () => {
    // This is the realistic case the offline-restore fix exists for:
    // wifi/mobile data is up (navigator.onLine is `true`), but this
    // specific self-hosted server isn't reachable from the current
    // network -- coffee-shop wifi, a different LAN, mobile data with no
    // route home. navigator.onLine never goes false here; only the
    // network-layer-failure signal does. A version of this fix gated on
    // `navigator.onLine` alone would incorrectly log the user out in
    // exactly this scenario.
    setNavigatorOnLine(true);
    window.localStorage.setItem(LAST_SYNCED_AT_KEY, "2026-08-10T12:00:00.000Z");
    mockRefreshAccessToken.mockResolvedValue(null);
    mockRefreshFailureWasNetworkError.mockReturnValue(true);

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

  it("leaves the session unauthenticated when refresh is explicitly rejected by a reachable server, even with a synced-at marker present", async () => {
    // The other half of the same fix: an explicit rejection (the server
    // was reached and said no -- e.g. a genuinely expired or revoked
    // refresh token) must never be swallowed by the offline-restore
    // fallback just because a stale synced-at marker happens to exist.
    // refreshFailureWasNetworkError() reporting `false` (the default) is
    // exactly what distinguishes this from the network-layer-failure case
    // above.
    setNavigatorOnLine(true);
    window.localStorage.setItem(LAST_SYNCED_AT_KEY, "2026-08-10T12:00:00.000Z");
    mockRefreshAccessToken.mockResolvedValue(null);
    mockRefreshFailureWasNetworkError.mockReturnValue(false);

    render(
      <AuthProvider>
        <Consumer />
      </AuthProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("loading")).toHaveTextContent("false"),
    );
    expect(screen.getByTestId("isAuthenticated")).toHaveTextContent("false");
    expect(mockRefreshAccessToken).toHaveBeenCalled();
  });

  it("throws when useAuth is called outside an AuthProvider", () => {
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() => render(<Consumer />)).toThrow(
      "useAuth must be used within an AuthProvider",
    );

    consoleErrorSpy.mockRestore();
  });
});

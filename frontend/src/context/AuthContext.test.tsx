import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

// Mocked in place of the real API client so tests control exactly when/how
// login and refresh resolve, without touching the network. Typed explicitly
// per this project's convention -- an untyped `vi.fn()` infers a zero-arg
// signature that `tsc -b` then rejects when the mock is called with args.
const mockLogin = vi.fn<(username: string, password: string) => Promise<void>>();
const mockRefreshAccessToken = vi.fn<() => Promise<string | null>>();
const mockSetAccessToken = vi.fn<(token: string | null) => void>();
let capturedRefreshFailureCallback: (() => void) | null = null;
const mockSetOnRefreshFailure = vi.fn<(callback: (() => void) | null) => void>(
  (callback) => {
    capturedRefreshFailureCallback = callback;
  },
);

vi.mock("../api/client", () => ({
  login: (username: string, password: string) => mockLogin(username, password),
  refreshAccessToken: () => mockRefreshAccessToken(),
  setAccessToken: (token: string | null) => mockSetAccessToken(token),
  setOnRefreshFailure: (callback: (() => void) | null) =>
    mockSetOnRefreshFailure(callback),
}));

import { AuthProvider, useAuth } from "./AuthContext";

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
  mockSetOnRefreshFailure.mockReset();
  mockSetOnRefreshFailure.mockImplementation((callback) => {
    capturedRefreshFailureCallback = callback;
  });
  capturedRefreshFailureCallback = null;
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

  it("throws when useAuth is called outside an AuthProvider", () => {
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() => render(<Consumer />)).toThrow(
      "useAuth must be used within an AuthProvider",
    );

    consoleErrorSpy.mockRestore();
  });
});

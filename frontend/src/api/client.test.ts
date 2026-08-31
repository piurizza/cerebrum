import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Regression coverage for review finding #1 (2026-08-31 code review): every
// other test file that touches this module mocks it entirely, so the real
// fetchWithToken()/refreshSession() network-vs-explicit-rejection
// classification logic (the mechanism the offline-mode plan's stated
// intent calls out by name -- "must not weaken auth") had never actually
// run under test. These tests drive it directly by stubbing global fetch,
// not the module.

// jsdom does not implement the Web Locks API -- refreshAccessToken() calls
// navigator.locks.request() to serialize refresh attempts across tabs (see
// client.ts's own docstring on why). Stubbed to just invoke the callback
// directly: these tests exercise the network-classification logic inside
// the callback, not the cross-tab locking behavior itself.
beforeEach(() => {
  Object.defineProperty(window.navigator, "locks", {
    configurable: true,
    value: {
      request: (_name: string, callback: () => Promise<unknown>) => callback(),
    },
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

// Each test gets a fresh module instance -- lastRefreshFailureWasNetworkError,
// the onNetworkFailure/onNetworkRecovery callbacks, and accessToken are all
// module-scoped singletons, and tests need to start from a known state
// rather than accumulating side effects from whichever test ran first.
async function freshClient() {
  vi.resetModules();
  return import("./client");
}

function jsonResponse(body: unknown, init: { status?: number } = {}) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("fetchWithToken() network classification", () => {
  it("fires onNetworkFailure and propagates the error when fetch() itself rejects", async () => {
    const client = await freshClient();
    const onFailure = vi.fn();
    const onRecovery = vi.fn();
    client.setOnNetworkStatusChange({ onFailure, onRecovery });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(client.listNotes()).rejects.toThrow("Failed to fetch");

    expect(onFailure).toHaveBeenCalledTimes(1);
    expect(onRecovery).not.toHaveBeenCalled();
  });

  it("fires onNetworkRecovery for any HTTP response, including a non-2xx one", async () => {
    const client = await freshClient();
    const onFailure = vi.fn();
    const onRecovery = vi.fn();
    client.setOnNetworkStatusChange({ onFailure, onRecovery });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "Not found" }, { status: 404 })),
    );

    await expect(client.listNotes()).rejects.toThrow("Not found");

    expect(onRecovery).toHaveBeenCalledTimes(1);
    expect(onFailure).not.toHaveBeenCalled();
  });

  it("aborts and reports a network failure when the request exceeds the fetch timeout", async () => {
    vi.useFakeTimers();
    const client = await freshClient();
    const onFailure = vi.fn();
    const onRecovery = vi.fn();
    client.setOnNetworkStatusChange({ onFailure, onRecovery });
    // Mirrors real fetch() behavior on abort: never resolves on its own,
    // rejects with an AbortError once the passed signal fires.
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) => {
        return new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("The operation was aborted.", "AbortError"));
          });
        });
      }),
    );

    const pending = client.listNotes();
    // Suppress the unhandled-rejection warning race between this
    // assignment and the timer advance below -- the real assertion is the
    // `rejects.toThrow()` on the same promise further down.
    pending.catch(() => {});
    await vi.advanceTimersByTimeAsync(15_000);

    await expect(pending).rejects.toThrow(/abort/i);
    expect(onFailure).toHaveBeenCalledTimes(1);
    expect(onRecovery).not.toHaveBeenCalled();
  });
});

describe("refreshSession() offline-restore classification (KTD0)", () => {
  it("a genuine network-layer failure sets refreshFailureWasNetworkError() to true", async () => {
    const client = await freshClient();
    const onFailure = vi.fn();
    client.setOnNetworkStatusChange({ onFailure, onRecovery: vi.fn() });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    const token = await client.refreshAccessToken();

    expect(token).toBeNull();
    expect(client.refreshFailureWasNetworkError()).toBe(true);
    expect(onFailure).toHaveBeenCalledTimes(1);
  });

  it("the refresh call's own timeout abort does NOT set refreshFailureWasNetworkError, even though it still signals the UI-facing offline banner (review finding #4)", async () => {
    vi.useFakeTimers();
    const client = await freshClient();
    const onFailure = vi.fn();
    client.setOnNetworkStatusChange({ onFailure, onRecovery: vi.fn() });
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) => {
        return new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("The operation was aborted.", "AbortError"));
          });
        });
      }),
    );

    const pending = client.refreshAccessToken();
    pending.catch(() => {});
    await vi.advanceTimersByTimeAsync(10_000);
    const token = await pending;

    expect(token).toBeNull();
    // The load-bearing assertion: a reachable-but-slow server (or a
    // network-path adversary who merely delays this one request past our
    // own timeout) must NOT be trusted for KTD0's offline-restore
    // concession -- only a genuine network-layer failure may.
    expect(client.refreshFailureWasNetworkError()).toBe(false);
    // Still surfaced as a UI-facing "can't reach it right now" signal --
    // a hang is real degradation worth reflecting in the offline banner,
    // just not trusted for the auth decision.
    expect(onFailure).toHaveBeenCalledTimes(1);
  });

  it("an explicit rejection from a reachable server resets refreshFailureWasNetworkError() to false, even from a prior true state", async () => {
    const client = await freshClient();
    const onFailure = vi.fn();
    const onRecovery = vi.fn();
    client.setOnNetworkStatusChange({ onFailure, onRecovery });
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    // First: a genuine network failure sets the flag true.
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await client.refreshAccessToken();
    expect(client.refreshFailureWasNetworkError()).toBe(true);

    // Then: a reachable server explicitly rejects the refresh (e.g. an
    // expired/revoked refresh-token cookie) -- a response DID come back,
    // so this must reset the flag, not leave the stale `true` from the
    // earlier failure in place.
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ detail: "unauthorized" }, { status: 401 }),
    );
    const token = await client.refreshAccessToken();

    expect(token).toBeNull();
    expect(client.refreshFailureWasNetworkError()).toBe(false);
    expect(onRecovery).toHaveBeenCalledTimes(1);
  });
});

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

function jsonResponse(
  body: unknown,
  init: { status?: number; headers?: Record<string, string> } = {},
) {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    headers: { "Content-Type": "application/json", ...init.headers },
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

  it("fires onNetworkRecovery for a 4xx response -- the server was reached and answered", async () => {
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

  it("fires onNetworkFailure for a 5xx on a GET -- nginx up but backend unreachable", async () => {
    const client = await freshClient();
    const onFailure = vi.fn();
    const onRecovery = vi.fn();
    client.setOnNetworkStatusChange({ onFailure, onRecovery });
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(jsonResponse({ detail: "Bad gateway" }, { status: 502 })),
    );

    await expect(client.listNotes()).rejects.toThrow(/Bad gateway|502/);

    expect(onFailure).toHaveBeenCalledTimes(1);
    expect(onRecovery).not.toHaveBeenCalled();
  });

  it("fires onNetworkRecovery for a 5xx on a WRITE -- a one-off write error must not flip the whole app offline", async () => {
    const client = await freshClient();
    const onFailure = vi.fn();
    const onRecovery = vi.fn();
    client.setOnNetworkStatusChange({ onFailure, onRecovery });
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse({ detail: "Service unavailable" }, { status: 503 }),
        ),
    );

    // The call still surfaces the error to its caller...
    await expect(client.putNote("note.md", "x")).rejects.toThrow(/unavailable|503/);
    // ...but the offline signal is not tripped by a write 5xx.
    expect(onRecovery).toHaveBeenCalledTimes(1);
    expect(onFailure).not.toHaveBeenCalled();
  });

  it("fires onNetworkFailure for a cache-served response (X-SW-Cache-Fallback), even at status 200", async () => {
    const client = await freshClient();
    const onFailure = vi.fn();
    const onRecovery = vi.fn();
    client.setOnNetworkStatusChange({ onFailure, onRecovery });
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse([], { headers: { "X-SW-Cache-Fallback": "1" } }),
        ),
    );

    await client.listNotes();

    // The service worker served this from cache during an outage -- the app
    // must treat it as "still offline", not as evidence the server is back.
    expect(onFailure).toHaveBeenCalledTimes(1);
    expect(onRecovery).not.toHaveBeenCalled();
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

describe("refreshFailureWasAuthRejection() -- reachable 401/403 vs everything else", () => {
  it("is false after a genuine network-layer failure (still a network error, not an auth verdict)", async () => {
    const client = await freshClient();
    client.setOnNetworkStatusChange({ onFailure: vi.fn(), onRecovery: vi.fn() });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await client.refreshAccessToken();

    expect(client.refreshFailureWasAuthRejection()).toBe(false);
    expect(client.refreshFailureWasNetworkError()).toBe(true);
  });

  it("is false after the refresh call's own timeout abort", async () => {
    vi.useFakeTimers();
    const client = await freshClient();
    client.setOnNetworkStatusChange({ onFailure: vi.fn(), onRecovery: vi.fn() });
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
    await pending;

    expect(client.refreshFailureWasAuthRejection()).toBe(false);
  });

  it("is true after a reachable server returns 401", async () => {
    const client = await freshClient();
    client.setOnNetworkStatusChange({ onFailure: vi.fn(), onRecovery: vi.fn() });
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(jsonResponse({ detail: "unauthorized" }, { status: 401 })),
    );

    const token = await client.refreshAccessToken();

    expect(token).toBeNull();
    expect(client.refreshFailureWasAuthRejection()).toBe(true);
  });

  it("is true after a reachable server returns 403", async () => {
    const client = await freshClient();
    client.setOnNetworkStatusChange({ onFailure: vi.fn(), onRecovery: vi.fn() });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ detail: "forbidden" }, { status: 403 })),
    );

    await client.refreshAccessToken();

    expect(client.refreshFailureWasAuthRejection()).toBe(true);
  });

  it("is false after a 5xx on refresh, and that 5xx fires onNetworkFailure (the mount-time trigger)", async () => {
    const client = await freshClient();
    const onFailure = vi.fn();
    const onRecovery = vi.fn();
    client.setOnNetworkStatusChange({ onFailure, onRecovery });
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(jsonResponse({ detail: "bad gateway" }, { status: 502 })),
    );

    const token = await client.refreshAccessToken();

    expect(token).toBeNull();
    expect(client.refreshFailureWasAuthRejection()).toBe(false);
    // refreshSession() is the deliberate carve-out from the GET-only 5xx
    // rule: it is the reliable onNetworkFailure trigger on mount.
    expect(onFailure).toHaveBeenCalledTimes(1);
    expect(onRecovery).not.toHaveBeenCalled();
  });

  it("is false after a successful refresh", async () => {
    const client = await freshClient();
    client.setOnNetworkStatusChange({ onFailure: vi.fn(), onRecovery: vi.fn() });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ access_token: "tok" })),
    );

    const token = await client.refreshAccessToken();

    expect(token).toBe("tok");
    expect(client.refreshFailureWasAuthRejection()).toBe(false);
  });

  it("resets to false when a later non-5xx response comes back, even from a prior true state", async () => {
    const client = await freshClient();
    client.setOnNetworkStatusChange({ onFailure: vi.fn(), onRecovery: vi.fn() });
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "no" }, { status: 401 }));
    await client.refreshAccessToken();
    expect(client.refreshFailureWasAuthRejection()).toBe(true);

    fetchMock.mockResolvedValueOnce(jsonResponse({ access_token: "tok" }));
    await client.refreshAccessToken();
    expect(client.refreshFailureWasAuthRejection()).toBe(false);
  });
});

describe("OIDC sign-in helpers", () => {
  function lastCall(fetchMock: ReturnType<typeof vi.fn>): [string, RequestInit] {
    const call = fetchMock.mock.calls.at(-1);
    if (!call) throw new Error("fetch was not called");
    return call as [string, RequestInit];
  }

  it("getAuthMethods() GETs /api/auth/methods and returns the body", async () => {
    const client = await freshClient();
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({ password_login: true, oidc: { provider_name: "Keycloak" } }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const methods = await client.getAuthMethods();

    expect(methods).toEqual({
      password_login: true,
      oidc: { provider_name: "Keycloak" },
    });
    const [url, init] = lastCall(fetchMock);
    expect(url).toBe("/api/auth/methods");
    expect(init.method ?? "GET").toBe("GET");
  });

  it("startOidc() POSTs the intent and fields as JSON and returns the authorization URL", async () => {
    const client = await freshClient();
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({ authorization_url: "https://idp.example/authorize?x=1" }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await client.startOidc({
      intent: "register",
      username: "ana",
      invite_token: "invite-123",
    });

    expect(result.authorization_url).toBe("https://idp.example/authorize?x=1");
    const [url, init] = lastCall(fetchMock);
    expect(url).toBe("/api/auth/oidc/start");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
    expect(JSON.parse(String(init.body))).toEqual({
      intent: "register",
      username: "ana",
      invite_token: "invite-123",
    });
  });

  it("startOidc() surfaces the server's detail as an ApiError (409 username taken)", async () => {
    const client = await freshClient();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse({ detail: "Username already taken" }, { status: 409 }),
        ),
    );

    const failure = client.startOidc({ intent: "register", username: "ana" });

    await expect(failure).rejects.toBeInstanceOf(client.ApiError);
    await expect(failure).rejects.toMatchObject({
      status: 409,
      message: "Username already taken",
    });
  });

  it("startOidc() for link sends the bearer token and does not refresh on a wrong-password 403", async () => {
    const client = await freshClient();
    client.setAccessToken("access-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        jsonResponse({ detail: "Current password is incorrect" }, { status: 403 }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      client.startOidc({ intent: "link", current_password: "wrong" }),
    ).rejects.toThrow("Current password is incorrect");

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = lastCall(fetchMock);
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer access-token");
  });

  it("getLinkedIdentity() GETs /api/account/identity", async () => {
    const client = await freshClient();
    const identity = {
      linked: true,
      provider_name: "Keycloak",
      display_name: "ana@example.com",
      has_password: true,
      password_usable: true,
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(identity));
    vi.stubGlobal("fetch", fetchMock);

    await expect(client.getLinkedIdentity()).resolves.toEqual(identity);
    expect(lastCall(fetchMock)[0]).toBe("/api/account/identity");
  });

  it("unlinkIdentity() DELETEs /api/account/identity and resolves on 204", async () => {
    const client = await freshClient();
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(client.unlinkIdentity()).resolves.toBeUndefined();
    const [url, init] = lastCall(fetchMock);
    expect(url).toBe("/api/account/identity");
    expect(init.method).toBe("DELETE");
  });

  it("unlinkIdentity() surfaces the 409 lock-out refusal", async () => {
    const client = await freshClient();
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          jsonResponse(
            { detail: "You need a password you can sign in with before unlinking" },
            { status: 409 },
          ),
        ),
    );

    await expect(client.unlinkIdentity()).rejects.toThrow(
      "You need a password you can sign in with before unlinking",
    );
  });
});

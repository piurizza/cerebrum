// Uses the default jsdom environment for `window.localStorage` and
// `navigator.onLine`, matching offline/sync.test.ts's stance on the same
// two globals.
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LAST_SYNCED_AT_KEY } from "../offline/sync";
import { setNavigatorOnLine } from "../test/factories";

// Captured directly rather than through a full client.ts mock -- this
// context's only dependency on the module is registering for this one
// callback pair, and capturing them lets tests invoke exactly what a real
// network failure/recovery would trigger.
let capturedNetworkCallbacks: {
  onFailure: () => void;
  onRecovery: () => void;
} | null = null;
const mockSetOnNetworkStatusChange = vi.fn(
  (callbacks: { onFailure: () => void; onRecovery: () => void } | null) => {
    capturedNetworkCallbacks = callbacks;
  },
);
vi.mock("../api/client", () => ({
  setOnNetworkStatusChange: (
    callbacks: { onFailure: () => void; onRecovery: () => void } | null,
  ) => mockSetOnNetworkStatusChange(callbacks),
}));

import { OfflineProvider, useOffline } from "./OfflineContext";

function Consumer() {
  const { isOffline, lastSyncedAt } = useOffline();
  return (
    <div>
      <div data-testid="isOffline">{String(isOffline)}</div>
      <div data-testid="lastSyncedAt">{lastSyncedAt ?? "null"}</div>
    </div>
  );
}

function renderProvider() {
  return render(
    <OfflineProvider>
      <Consumer />
    </OfflineProvider>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  setNavigatorOnLine(true);
  mockSetOnNetworkStatusChange.mockClear();
  capturedNetworkCallbacks = null;
});

afterEach(() => {
  setNavigatorOnLine(true);
});

describe("OfflineProvider", () => {
  it("seeds isOffline from navigator.onLine at mount", () => {
    setNavigatorOnLine(false);

    renderProvider();

    expect(screen.getByTestId("isOffline")).toHaveTextContent("true");
  });

  it("seeds isOffline as false when navigator.onLine is true at mount", () => {
    setNavigatorOnLine(true);

    renderProvider();

    expect(screen.getByTestId("isOffline")).toHaveTextContent("false");
  });

  it("seeds lastSyncedAt from localStorage at mount", () => {
    window.localStorage.setItem(LAST_SYNCED_AT_KEY, "2026-08-10T12:00:00.000Z");

    renderProvider();

    expect(screen.getByTestId("lastSyncedAt")).toHaveTextContent(
      "2026-08-10T12:00:00.000Z",
    );
  });

  it("seeds lastSyncedAt as null when localStorage has no synced-at entry", () => {
    renderProvider();

    expect(screen.getByTestId("lastSyncedAt")).toHaveTextContent("null");
  });

  it("flips isOffline to true when a live offline event fires", () => {
    renderProvider();
    expect(screen.getByTestId("isOffline")).toHaveTextContent("false");

    act(() => {
      setNavigatorOnLine(false);
      window.dispatchEvent(new Event("offline"));
    });

    expect(screen.getByTestId("isOffline")).toHaveTextContent("true");
  });

  it("flips isOffline back to false when a live online event fires", () => {
    setNavigatorOnLine(false);
    renderProvider();
    expect(screen.getByTestId("isOffline")).toHaveTextContent("true");

    act(() => {
      setNavigatorOnLine(true);
      window.dispatchEvent(new Event("online"));
    });

    expect(screen.getByTestId("isOffline")).toHaveTextContent("false");
  });

  it("re-reads lastSyncedAt from localStorage when a live online event fires", () => {
    setNavigatorOnLine(false);
    renderProvider();
    expect(screen.getByTestId("lastSyncedAt")).toHaveTextContent("null");

    window.localStorage.setItem(LAST_SYNCED_AT_KEY, "2026-08-14T08:30:00.000Z");
    act(() => {
      setNavigatorOnLine(true);
      window.dispatchEvent(new Event("online"));
    });

    expect(screen.getByTestId("lastSyncedAt")).toHaveTextContent(
      "2026-08-14T08:30:00.000Z",
    );
  });

  it("re-reads lastSyncedAt from localStorage when a live offline event fires", () => {
    // A sync fired from main.tsx can complete after this provider's
    // mount-time seed (both happen on the same app load), so the first
    // "offline" event in a session must also pick up a sync that landed
    // in between -- not just the "online" handler on the *next* reconnect.
    renderProvider();
    expect(screen.getByTestId("lastSyncedAt")).toHaveTextContent("null");

    window.localStorage.setItem(LAST_SYNCED_AT_KEY, "2026-08-14T09:00:00.000Z");
    act(() => {
      setNavigatorOnLine(false);
      window.dispatchEvent(new Event("offline"));
    });

    expect(screen.getByTestId("lastSyncedAt")).toHaveTextContent(
      "2026-08-14T09:00:00.000Z",
    );
  });

  it("flips isOffline to true when a real request fails at the network layer, even though navigator.onLine stays true", () => {
    // The scenario this closes: the device's own network interface is up
    // (navigator.onLine never goes false) but the configured server
    // itself is unreachable -- verified live against the real desktop
    // app (a docker container going down while the host's wifi stayed
    // up). A flag driven by navigator.onLine alone would miss this
    // entirely.
    renderProvider();
    expect(screen.getByTestId("isOffline")).toHaveTextContent("false");

    act(() => {
      capturedNetworkCallbacks?.onFailure();
    });

    expect(screen.getByTestId("isOffline")).toHaveTextContent("true");
    expect(navigator.onLine).toBe(true);
  });

  it("flips isOffline back to false when a real request recovers", () => {
    renderProvider();
    act(() => {
      capturedNetworkCallbacks?.onFailure();
    });
    expect(screen.getByTestId("isOffline")).toHaveTextContent("true");

    act(() => {
      capturedNetworkCallbacks?.onRecovery();
    });

    expect(screen.getByTestId("isOffline")).toHaveTextContent("false");
  });

  it("registers and unregisters its network-status callback across mount/unmount", () => {
    const { unmount } = renderProvider();
    expect(mockSetOnNetworkStatusChange).toHaveBeenCalledWith(
      expect.objectContaining({
        onFailure: expect.any(Function),
        onRecovery: expect.any(Function),
      }),
    );

    unmount();

    expect(mockSetOnNetworkStatusChange).toHaveBeenLastCalledWith(null);
  });

  it("removes its online/offline listeners on unmount", () => {
    const addSpy = vi.spyOn(window, "addEventListener");
    const removeSpy = vi.spyOn(window, "removeEventListener");

    const { unmount } = renderProvider();
    const addedEvents = addSpy.mock.calls
      .map(([type]) => type)
      .filter((type) => type === "online" || type === "offline");
    expect(addedEvents).toEqual(["online", "offline"]);

    unmount();

    const removedEvents = removeSpy.mock.calls
      .map(([type]) => type)
      .filter((type) => type === "online" || type === "offline");
    expect(removedEvents).toEqual(["online", "offline"]);

    addSpy.mockRestore();
    removeSpy.mockRestore();
  });

  it("throws when useOffline is called outside an OfflineProvider", () => {
    const consoleErrorSpy = vi.spyOn(console, "error").mockImplementation(() => {});

    expect(() => render(<Consumer />)).toThrow(
      "useOffline must be used within an OfflineProvider",
    );

    consoleErrorSpy.mockRestore();
  });
});

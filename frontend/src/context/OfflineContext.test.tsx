// Uses the default jsdom environment for `window.localStorage` and
// `navigator.onLine`, matching offline/sync.test.ts's stance on the same
// two globals.
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LAST_SYNCED_AT_KEY } from "../offline/sync";
import { OfflineProvider, useOffline } from "./OfflineContext";

function setNavigatorOnLine(value: boolean) {
  Object.defineProperty(window.navigator, "onLine", {
    configurable: true,
    value,
  });
}

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

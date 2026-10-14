import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { makeNoteMeta } from "../test/factories";

// Only listNotes is mocked -- this test renders the real NotesProvider,
// unlike NoteBrowser.test.tsx (which mocks useNotes wholesale). That's
// deliberate here: the point of this file is to prove the provider
// itself produces the right `loading` transition, not just that a
// consumer reacts correctly to a hand-fed value.
const mockListNotes = vi.fn();
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, listNotes: () => mockListNotes() };
});

import { NotesProvider, useNotes } from "./NotesContext";

let refreshFromConsumer: (() => Promise<void>) | null = null;

function Consumer() {
  const { notes, error, loading, refreshNotes } = useNotes();
  refreshFromConsumer = refreshNotes;
  return (
    <div>
      <div data-testid="loading">{String(loading)}</div>
      <div data-testid="error">{error ?? "null"}</div>
      <div data-testid="count">{notes.length}</div>
      <div data-testid="paths">{notes.map((note) => note.path).join(",")}</div>
    </div>
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function setVisibility(state: DocumentVisibilityState) {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
}

async function renderSettled() {
  render(
    <NotesProvider>
      <Consumer />
    </NotesProvider>,
  );
  await waitFor(() => expect(screen.getByTestId("loading")).toHaveTextContent("false"));
}

beforeEach(() => {
  mockListNotes.mockReset();
  setVisibility("visible");
});

afterEach(() => {
  setVisibility("visible");
  vi.restoreAllMocks();
});

describe("NotesProvider loading", () => {
  it("starts loading and settles false with notes on a successful fetch", async () => {
    mockListNotes.mockResolvedValue([makeNoteMeta("a.md"), makeNoteMeta("b.md")]);

    render(
      <NotesProvider>
        <Consumer />
      </NotesProvider>,
    );

    // The fetch is already in flight by the time render() returns
    // (kicked off from a useEffect on mount), so loading starts true.
    expect(screen.getByTestId("loading")).toHaveTextContent("true");

    await waitFor(() =>
      expect(screen.getByTestId("loading")).toHaveTextContent("false"),
    );
    expect(screen.getByTestId("count")).toHaveTextContent("2");
    expect(screen.getByTestId("error")).toHaveTextContent("null");
  });

  it("settles loading false even when the fetch fails", async () => {
    mockListNotes.mockRejectedValue(new Error("network error"));

    render(
      <NotesProvider>
        <Consumer />
      </NotesProvider>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("loading")).toHaveTextContent("false"),
    );
    expect(screen.getByTestId("error")).toHaveTextContent("network error");
    expect(screen.getByTestId("count")).toHaveTextContent("0");
  });
});

describe("NotesProvider background refresh", () => {
  it("refetches when the window regains focus", async () => {
    mockListNotes.mockResolvedValueOnce([makeNoteMeta("a.md")]);
    await renderSettled();
    mockListNotes.mockResolvedValueOnce([makeNoteMeta("a.md"), makeNoteMeta("new.md")]);

    act(() => {
      window.dispatchEvent(new Event("focus"));
    });

    await waitFor(() =>
      expect(screen.getByTestId("paths")).toHaveTextContent("a.md,new.md"),
    );
    expect(mockListNotes).toHaveBeenCalledTimes(2);
  });

  it("refetches when the document becomes visible", async () => {
    mockListNotes.mockResolvedValueOnce([makeNoteMeta("a.md")]);
    await renderSettled();
    mockListNotes.mockResolvedValueOnce([makeNoteMeta("b.md")]);

    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    await waitFor(() => expect(screen.getByTestId("paths")).toHaveTextContent("b.md"));
  });

  it("does not refetch when the document becomes hidden", async () => {
    mockListNotes.mockResolvedValueOnce([makeNoteMeta("a.md")]);
    await renderSettled();

    setVisibility("hidden");
    act(() => {
      document.dispatchEvent(new Event("visibilitychange"));
    });

    expect(mockListNotes).toHaveBeenCalledTimes(1);
  });

  it("collapses focus and visibilitychange into one request while it is in flight", async () => {
    mockListNotes.mockResolvedValueOnce([makeNoteMeta("a.md")]);
    await renderSettled();
    const pending = deferred<ReturnType<typeof makeNoteMeta>[]>();
    mockListNotes.mockReturnValueOnce(pending.promise);

    act(() => {
      window.dispatchEvent(new Event("focus"));
      document.dispatchEvent(new Event("visibilitychange"));
    });
    expect(mockListNotes).toHaveBeenCalledTimes(2);

    await act(async () => {
      pending.resolve([makeNoteMeta("b.md")]);
      await pending.promise;
    });
    expect(screen.getByTestId("paths")).toHaveTextContent("b.md");
  });

  it("keeps the newer list when an older background response lands last", async () => {
    mockListNotes.mockResolvedValueOnce([makeNoteMeta("a.md")]);
    await renderSettled();
    const stale = deferred<ReturnType<typeof makeNoteMeta>[]>();
    mockListNotes.mockReturnValueOnce(stale.promise);
    mockListNotes.mockResolvedValueOnce([
      makeNoteMeta("a.md"),
      makeNoteMeta("today.md"),
    ]);

    act(() => {
      window.dispatchEvent(new Event("focus"));
    });
    await act(async () => {
      await refreshFromConsumer?.();
    });
    expect(screen.getByTestId("paths")).toHaveTextContent("a.md,today.md");

    await act(async () => {
      stale.resolve([makeNoteMeta("a.md")]);
      await stale.promise;
    });
    expect(screen.getByTestId("paths")).toHaveTextContent("a.md,today.md");
  });

  it("keeps the last good list when a background refresh fails", async () => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    mockListNotes.mockResolvedValueOnce([makeNoteMeta("a.md")]);
    await renderSettled();
    mockListNotes.mockRejectedValueOnce(new Error("network error"));

    await act(async () => {
      window.dispatchEvent(new Event("focus"));
    });

    await waitFor(() => expect(console.warn).toHaveBeenCalled());
    expect(screen.getByTestId("error")).toHaveTextContent("null");
    expect(screen.getByTestId("paths")).toHaveTextContent("a.md");
  });

  it("clears an initial load error once a background refresh succeeds", async () => {
    mockListNotes.mockRejectedValueOnce(new Error("network error"));
    await renderSettled();
    expect(screen.getByTestId("error")).toHaveTextContent("network error");
    mockListNotes.mockResolvedValueOnce([makeNoteMeta("a.md")]);

    act(() => {
      window.dispatchEvent(new Event("focus"));
    });

    await waitFor(() => expect(screen.getByTestId("error")).toHaveTextContent("null"));
    expect(screen.getByTestId("paths")).toHaveTextContent("a.md");
  });
});

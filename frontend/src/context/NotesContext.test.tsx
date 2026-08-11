import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
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

function Consumer() {
  const { notes, error, loading } = useNotes();
  return (
    <div>
      <div data-testid="loading">{String(loading)}</div>
      <div data-testid="error">{error ?? "null"}</div>
      <div data-testid="count">{notes.length}</div>
    </div>
  );
}

beforeEach(() => {
  mockListNotes.mockReset();
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

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { makeNoteMeta } from "../../test/factories";
import type { NoteMeta } from "../../types/note";

// `getTodayNotePath`/`getDailyNoteDefaultBody` have their own dedicated
// test file (dailyNote.test.ts) -- here they're stubbed to sentinel
// values so this file can assert on *wiring* (does the computed path
// drive the existence check / putNote call / navigation) without
// re-testing their internals, matching MarkdownEditor.test.tsx's
// established pattern for imagePasteExtension/noteLinkCompletionSource.
const TODAY_PATH = "daily/2026-08-11.md";
const TODAY_BODY = "# Tuesday, August 11, 2026\n\n";
vi.mock("../../lib/dailyNote", () => ({
  getTodayNotePath: () => TODAY_PATH,
  getDailyNoteDefaultBody: () => TODAY_BODY,
}));

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return { ...actual, useNavigate: () => mockNavigate };
});

const mockPutNote = vi.fn<(path: string, content: string) => Promise<unknown>>();
vi.mock("../../api/client", async () => {
  const actual =
    await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return {
    ...actual,
    putNote: (path: string, content: string) => mockPutNote(path, content),
  };
});

const mockUseNotes =
  vi.fn<
    () => {
      notes: NoteMeta[];
      error: string | null;
      loading: boolean;
      refreshNotes: () => void;
    }
  >();
vi.mock("../../context/NotesContext", () => ({
  useNotes: () => mockUseNotes(),
}));

import { NoteBrowser } from "./NoteBrowser";

const refreshNotes = vi.fn();

function setNotesState(notes: NoteMeta[], overrides: { loading?: boolean } = {}) {
  mockUseNotes.mockReturnValue({
    notes,
    error: null,
    loading: overrides.loading ?? false,
    refreshNotes,
  });
}

// NoteBrowser renders NoteTreeList, which uses NavLink -- that needs a
// Router context to render, matching BacklinksPanel.test.tsx's pattern.
function renderBrowser() {
  return render(
    <MemoryRouter>
      <NoteBrowser />
    </MemoryRouter>,
  );
}

describe("NoteBrowser Today button", () => {
  beforeEach(() => {
    mockNavigate.mockReset();
    mockPutNote.mockReset();
    refreshNotes.mockReset();
  });

  it("creates today's note and navigates when it does not exist yet", async () => {
    const user = userEvent.setup();
    setNotesState([makeNoteMeta("other.md")]);
    mockPutNote.mockResolvedValue({});

    renderBrowser();
    await user.click(screen.getByRole("button", { name: "Today" }));

    await waitFor(() =>
      expect(mockPutNote).toHaveBeenCalledWith(TODAY_PATH, TODAY_BODY),
    );
    expect(refreshNotes).toHaveBeenCalled();
    expect(mockNavigate).toHaveBeenCalledWith("/notes/daily/2026-08-11.md");
  });

  it("navigates directly without calling putNote when today's note already exists", async () => {
    const user = userEvent.setup();
    setNotesState([makeNoteMeta(TODAY_PATH)]);

    renderBrowser();
    await user.click(screen.getByRole("button", { name: "Today" }));

    expect(mockPutNote).not.toHaveBeenCalled();
    expect(mockNavigate).toHaveBeenCalledWith("/notes/daily/2026-08-11.md");
  });

  it("does not fire a second putNote call on a rapid second click", async () => {
    const user = userEvent.setup();
    setNotesState([]);
    let resolvePutNote!: (value: unknown) => void;
    mockPutNote.mockReturnValue(
      new Promise((resolve) => {
        resolvePutNote = resolve;
      }),
    );

    renderBrowser();
    const button = screen.getByRole("button", { name: "Today" });
    await user.click(button);
    // The button disables itself synchronously once the async branch
    // starts, before putNote resolves -- a second click here must be a
    // no-op, proving the in-flight guard actually prevents the
    // overwrite this feature exists to avoid.
    await user.click(button);

    expect(mockPutNote).toHaveBeenCalledTimes(1);
    resolvePutNote({});
  });

  it("is a no-op while the initial notes fetch is still loading", async () => {
    const user = userEvent.setup();
    setNotesState([], { loading: true });

    renderBrowser();
    await user.click(screen.getByRole("button", { name: "Today" }));

    expect(mockPutNote).not.toHaveBeenCalled();
    expect(mockNavigate).not.toHaveBeenCalled();
  });

  it("renders a putNote failure visibly and does not navigate", async () => {
    const user = userEvent.setup();
    setNotesState([]);
    mockPutNote.mockRejectedValue(new Error("network error"));

    renderBrowser();
    await user.click(screen.getByRole("button", { name: "Today" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("network error");
    expect(mockNavigate).not.toHaveBeenCalled();
  });
});

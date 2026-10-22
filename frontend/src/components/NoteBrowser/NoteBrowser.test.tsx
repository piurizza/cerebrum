import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { loadVaultSettings } from "../../lib/vaultSettings";
import { makeNoteMeta, setCachedVaultReadOnly } from "../../test/factories";
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
const mockGetNote = vi.fn<(path: string) => Promise<{ content: string }>>();
const mockGetVaultSettings = vi.fn<() => Promise<unknown>>();
vi.mock("../../api/client", async () => {
  const actual =
    await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return {
    ...actual,
    putNote: (path: string, content: string) => mockPutNote(path, content),
    getNote: (path: string) => mockGetNote(path),
    getVaultSettings: () => mockGetVaultSettings(),
  };
});

const mockUseNotes =
  vi.fn<
    () => {
      notes: NoteMeta[];
      error: string | null;
      loading: boolean;
      refreshNotes: () => Promise<void>;
    }
  >();
vi.mock("../../context/NotesContext", () => ({
  useNotes: () => mockUseNotes(),
}));

const mockUseOffline =
  vi.fn<() => { isOffline: boolean; lastSyncedAt: string | null }>();
vi.mock("../../context/OfflineContext", () => ({
  useOffline: () => mockUseOffline(),
}));

import { NoteBrowser } from "./NoteBrowser";

const refreshNotes = vi.fn<() => Promise<void>>().mockResolvedValue(undefined);

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

// Applies to every describe block below: none of them are exercising
// offline behavior, so default to "online" and let the individual test
// that cares override it.
beforeEach(() => {
  mockUseOffline.mockReset();
  mockUseOffline.mockReturnValue({ isOffline: false, lastSyncedAt: null });
  // Never fetched: counts as writable.
  setCachedVaultReadOnly(null);
});

describe("NoteBrowser Today button", () => {
  beforeEach(() => {
    mockNavigate.mockReset();
    mockPutNote.mockReset();
    // mockClear, not mockReset: keeps the module-scope
    // .mockResolvedValue(undefined) in place across tests, only
    // clearing call history.
    refreshNotes.mockClear();
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
    // Proves the `finally` block's isOpeningToday reset actually runs on
    // the error path too, not just on success -- otherwise the button
    // would stay disabled forever after any failure, with no way to
    // retry.
    expect(screen.getByRole("button", { name: "Today" })).toBeEnabled();
  });
});

// Drives the real FolderPickerModal and TemplatePickerModal (neither is
// mocked) -- only the API layer and notes list are controlled -- so these
// tests exercise the actual U1/U2/U3 wiring together, not a reimplementation
// of it.
describe("NoteBrowser + New note / templates", () => {
  beforeEach(() => {
    mockNavigate.mockReset();
    mockPutNote.mockReset();
    mockGetNote.mockReset();
    refreshNotes.mockClear();
  });

  async function createNoteViaPicker(
    user: ReturnType<typeof userEvent.setup>,
    filename: string,
  ) {
    await user.click(screen.getByRole("button", { name: "+ New note" }));
    await user.type(screen.getByPlaceholderText("note.md"), filename);
    await user.click(screen.getByRole("button", { name: "Create" }));
  }

  it("disables + New note while the initial notes fetch is still loading", () => {
    // Regression guard: opening the picker before `notes` has loaded
    // would make handleCreate's template-relevance check run against an
    // empty list and silently skip the picker even when a relevant
    // template genuinely exists once loading finishes.
    setNotesState([], { loading: true });

    renderBrowser();

    expect(screen.getByRole("button", { name: "+ New note" })).toBeDisabled();
  });

  it("creates a blank note exactly as before when the vault has zero templates", async () => {
    const user = userEvent.setup();
    setNotesState([makeNoteMeta("other.md")]);
    mockPutNote.mockResolvedValue({});

    renderBrowser();
    await createNoteViaPicker(user, "note1.md");

    await waitFor(() => expect(mockPutNote).toHaveBeenCalledWith("note1.md", ""));
    expect(mockGetNote).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog", { name: "Choose a template" })).toBeNull();
    expect(mockNavigate).toHaveBeenCalledWith("/notes/note1.md");
  });

  it("creates a blank note when every template is other-scope for the target folder (R3 skip rule)", async () => {
    const user = userEvent.setup();
    // A scoped-only template, created at the vault root -- root has no
    // path segments to match "standup" against, so this is other-scope,
    // not relevant, and the picker should never open.
    setNotesState([makeNoteMeta("templates/standup/Standup.md")]);
    mockPutNote.mockResolvedValue({});

    renderBrowser();
    await createNoteViaPicker(user, "note1.md");

    await waitFor(() => expect(mockPutNote).toHaveBeenCalledWith("note1.md", ""));
    expect(screen.queryByRole("dialog", { name: "Choose a template" })).toBeNull();
  });

  it("opens the template picker when a relevant (global) template exists", async () => {
    const user = userEvent.setup();
    setNotesState([makeNoteMeta("templates/Meeting.md")]);

    renderBrowser();
    await createNoteViaPicker(user, "note1.md");

    expect(
      screen.getByRole("dialog", { name: "Choose a template" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Meeting")).toBeInTheDocument();
    expect(mockPutNote).not.toHaveBeenCalled();
  });

  it("creates the note with the template's content stripped of title/created when selected and confirmed", async () => {
    const user = userEvent.setup();
    setNotesState([makeNoteMeta("templates/Meeting.md")]);
    mockGetNote.mockResolvedValue({
      content:
        "---\ntitle: Meeting\ntags: [work]\ncreated: '2026-01-01T00:00:00+00:00'\n---\n# Agenda\n\nItems.",
    });
    mockPutNote.mockResolvedValue({});

    renderBrowser();
    await createNoteViaPicker(user, "note1.md");
    await user.click(screen.getByLabelText("Meeting"));
    await user.click(screen.getByRole("button", { name: "Create note" }));

    expect(mockGetNote).toHaveBeenCalledWith("templates/Meeting.md");
    await waitFor(() =>
      expect(mockPutNote).toHaveBeenCalledWith(
        "note1.md",
        "---\ntags: [work]\n---\n# Agenda\n\nItems.",
      ),
    );
    expect(refreshNotes).toHaveBeenCalled();
    expect(mockNavigate).toHaveBeenCalledWith("/notes/note1.md");
  });

  it("creates a blank note when Blank note is confirmed despite templates existing", async () => {
    const user = userEvent.setup();
    setNotesState([makeNoteMeta("templates/Meeting.md")]);
    mockPutNote.mockResolvedValue({});

    renderBrowser();
    await createNoteViaPicker(user, "note1.md");
    await user.click(screen.getByRole("button", { name: "Create note" }));

    expect(mockGetNote).not.toHaveBeenCalled();
    await waitFor(() => expect(mockPutNote).toHaveBeenCalledWith("note1.md", ""));
    expect(mockNavigate).toHaveBeenCalledWith("/notes/note1.md");
  });

  it("does not fire a second getNote/putNote pair on a rapid second confirm click", async () => {
    const user = userEvent.setup();
    setNotesState([makeNoteMeta("templates/Meeting.md")]);
    let resolveGetNote!: (value: { content: string }) => void;
    mockGetNote.mockReturnValue(
      new Promise((resolve) => {
        resolveGetNote = resolve;
      }),
    );

    renderBrowser();
    await createNoteViaPicker(user, "note1.md");
    await user.click(screen.getByLabelText("Meeting"));
    const confirmButton = screen.getByRole("button", { name: "Create note" });
    await user.click(confirmButton);
    // The Confirm button disables synchronously once the async branch
    // starts, before getNote resolves -- a second click here must be a
    // no-op.
    await user.click(confirmButton);

    expect(mockGetNote).toHaveBeenCalledTimes(1);
    resolveGetNote({ content: "Body." });
  });

  it("re-checks 'already exists' at confirm time and surfaces the error via the picker, without calling putNote", async () => {
    const user = userEvent.setup();
    setNotesState([makeNoteMeta("templates/Meeting.md"), makeNoteMeta("existing.md")]);

    renderBrowser();
    await createNoteViaPicker(user, "existing.md");
    await user.click(screen.getByRole("button", { name: "Create note" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      'A note already exists at "existing.md".',
    );
    expect(mockPutNote).not.toHaveBeenCalled();
    expect(
      screen.getByRole("dialog", { name: "Choose a template" }),
    ).toBeInTheDocument();
  });

  it("surfaces a getNote failure via the picker's error prop, not the top-level createError, and does not navigate", async () => {
    const user = userEvent.setup();
    setNotesState([makeNoteMeta("templates/Meeting.md")]);
    mockGetNote.mockRejectedValue(new Error("network error"));

    renderBrowser();
    await createNoteViaPicker(user, "note1.md");
    await user.click(screen.getByLabelText("Meeting"));
    await user.click(screen.getByRole("button", { name: "Create note" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("network error");
    expect(mockNavigate).not.toHaveBeenCalled();
    // Proves the finally block's isCreatingNote reset runs on the error
    // path too, not just on success -- otherwise Create note would stay
    // disabled forever after any failure, with no way to retry (mirrors
    // the equivalent isOpeningToday assertion in the Today-button tests).
    expect(screen.getByRole("button", { name: "Create note" })).toBeEnabled();
    // Still the picker, not a full-sidebar replacement: the sidebar's
    // other chrome (search input) is still present alongside the alert.
    expect(screen.getByPlaceholderText("Search notes...")).toBeInTheDocument();
    expect(
      screen.getByRole("dialog", { name: "Choose a template" }),
    ).toBeInTheDocument();
  });

  it("creates no note and leaves no pending state when the template picker is cancelled", async () => {
    const user = userEvent.setup();
    setNotesState([makeNoteMeta("templates/Meeting.md")]);
    mockPutNote.mockResolvedValue({});

    renderBrowser();
    await createNoteViaPicker(user, "note1.md");
    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog", { name: "Choose a template" })).toBeNull();
    expect(mockPutNote).not.toHaveBeenCalled();
    expect(mockGetNote).not.toHaveBeenCalled();

    // No stale pending state: creating the same path again from scratch
    // still works normally.
    await createNoteViaPicker(user, "note1.md");
    await user.click(screen.getByRole("button", { name: "Create note" }));
    await waitFor(() => expect(mockPutNote).toHaveBeenCalledWith("note1.md", ""));
  });
});

// Regression coverage for review finding #3 (2026-08-31 code review): the
// beforeEach above always sets isOffline: false, so nothing previously
// exercised the `|| isOffline` half of either button's disabled
// expression -- a change that silently dropped it would have passed the
// full suite.
describe("NoteBrowser offline gating (R3)", () => {
  it("disables both Today and + New note while offline", () => {
    setNotesState([makeNoteMeta("other.md")]);
    mockUseOffline.mockReturnValue({ isOffline: true, lastSyncedAt: null });

    renderBrowser();

    expect(screen.getByRole("button", { name: "Today" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "+ New note" })).toBeDisabled();
  });

  it("re-enables both buttons once back online", () => {
    setNotesState([makeNoteMeta("other.md")]);
    mockUseOffline.mockReturnValue({ isOffline: false, lastSyncedAt: null });

    renderBrowser();

    expect(screen.getByRole("button", { name: "Today" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "+ New note" })).toBeEnabled();
  });

  // Defense in depth (U5): `writeNoteAndNavigate` and `handleToday`
  // early-return on `isOffline` *before* their `putNote`, mirroring
  // `NoteViewPage.handleBlockedSave`, so a create/template modal opened
  // while online cannot issue a write if its Confirm is clicked after
  // connectivity drops. `handleToday`'s guard sits AFTER its
  // `noteExistsAt(path)` -> navigate branch, so "navigates directly
  // without calling putNote when today's note already exists" above still
  // proves an offline user keeps the cached-note shortcut.
  //
  // Regression coverage for review finding #2 (2026-09-07 code review):
  // the guard originally read the closed-over `isOffline` binding, which
  // is stale by the time `handleTemplateConfirm`'s own `await
  // getNote(templatePath)` resolves -- a connectivity drop mid-await was
  // invisible to it. Now that the guard reads a live ref, this transition
  // is reproducible: flip `isOffline` and rerender while `getNote` is
  // still pending, before letting it resolve.
  it("does not call putNote if isOffline flips true while handleTemplateConfirm's own getNote() is still pending", async () => {
    const user = userEvent.setup();
    // This describe block has no beforeEach resetting these -- unlike
    // "NoteBrowser + New note / templates" above, which does per-test. Clear
    // call history left over from whichever test last touched them.
    mockPutNote.mockClear();
    mockGetNote.mockReset();
    setNotesState([makeNoteMeta("templates/Meeting.md")]);
    let resolveGetNote!: (value: { content: string }) => void;
    mockGetNote.mockReturnValue(
      new Promise((resolve) => {
        resolveGetNote = resolve;
      }),
    );

    const { rerender } = renderBrowser();
    await user.click(screen.getByRole("button", { name: "+ New note" }));
    await user.type(screen.getByPlaceholderText("note.md"), "note1.md");
    await user.click(screen.getByRole("button", { name: "Create" }));
    await user.click(screen.getByLabelText("Meeting"));
    await user.click(screen.getByRole("button", { name: "Create note" }));

    // Connectivity drops while getNote() is still in flight -- rerender so
    // the ref (not just the mock's return value) actually updates.
    mockUseOffline.mockReturnValue({ isOffline: true, lastSyncedAt: null });
    rerender(
      <MemoryRouter>
        <NoteBrowser />
      </MemoryRouter>,
    );

    await act(async () => {
      resolveGetNote({ content: "# Agenda\n\nItems." });
      await Promise.resolve();
    });

    expect(mockPutNote).not.toHaveBeenCalled();
  });
});

// Read-only vault (CEREBRUM_VAULT_READ_ONLY): the create controls are
// permanently unavailable, so they are hidden rather than disabled --
// unlike offline above, which is temporary and keeps them visible.
describe("NoteBrowser read-only vault", () => {
  it("hides Today and + New note when the vault is read-only", () => {
    setNotesState([makeNoteMeta("other.md")]);
    setCachedVaultReadOnly(true);

    renderBrowser();

    expect(screen.queryByRole("button", { name: "Today" })).toBeNull();
    expect(screen.queryByRole("button", { name: "+ New note" })).toBeNull();
    // Browsing still works.
    expect(screen.getByPlaceholderText("Search notes...")).toBeInTheDocument();
  });

  it("hides them, not just disables them, when read-only and offline at once", () => {
    setNotesState([makeNoteMeta("other.md")]);
    setCachedVaultReadOnly(true);
    mockUseOffline.mockReturnValue({ isOffline: true, lastSyncedAt: null });

    renderBrowser();

    expect(screen.queryByRole("button", { name: "Today" })).toBeNull();
    expect(screen.queryByRole("button", { name: "+ New note" })).toBeNull();
  });

  it("shows both when the vault is known to be writable", () => {
    setNotesState([makeNoteMeta("other.md")]);
    setCachedVaultReadOnly(false);

    renderBrowser();

    expect(screen.getByRole("button", { name: "Today" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "+ New note" })).toBeEnabled();
  });

  it("closes the template picker without writing when the vault turns out to be read-only", async () => {
    const user = userEvent.setup();
    mockPutNote.mockClear();
    mockGetNote.mockReset();
    mockGetNote.mockResolvedValue({ content: "# Agenda" });
    setNotesState([makeNoteMeta("templates/Meeting.md")]);

    renderBrowser();
    await user.click(screen.getByRole("button", { name: "+ New note" }));
    await user.type(screen.getByPlaceholderText("note.md"), "note1.md");
    await user.click(screen.getByRole("button", { name: "Create" }));
    expect(
      screen.getByRole("dialog", { name: "Choose a template" }),
    ).toBeInTheDocument();

    // The first-visit vault-settings load lands while the picker is open.
    mockGetVaultSettings.mockResolvedValue({ read_only: true });
    await act(async () => {
      await loadVaultSettings();
    });

    expect(screen.queryByRole("dialog", { name: "Choose a template" })).toBeNull();
    expect(screen.queryByRole("button", { name: "+ New note" })).toBeNull();
    expect(mockPutNote).not.toHaveBeenCalled();
  });
});

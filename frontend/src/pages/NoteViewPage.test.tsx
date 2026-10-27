import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, CachedNoteError, NoteConflictError } from "../api/client";
import { localIsoDate } from "../lib/dailyNote";
import { TASK_CHANGED_MESSAGE } from "../lib/tasks";
import { loadVaultSettings } from "../lib/vaultSettings";
import { setCachedVaultReadOnly } from "../test/factories";
import type { Note, SetTaskDoneRequest, TaskItem } from "../types/note";

const TEST_PATH = "notes/a.md";

function makeNote(overrides: Partial<Note> = {}): Note {
  return {
    path: TEST_PATH,
    title: "A",
    tags: [],
    created: "2026-08-01T00:00:00.000Z",
    updated: "2026-08-01T00:00:00.000Z",
    content: "Hello world",
    version: "version-1",
    ...overrides,
  };
}

// Only getNote/getLiveNote/putNote/getBacklinks touch the network from
// this page's tree; encodeNotePath/errorMessage are real logic worth
// exercising as-is (matches TasksPage.test.tsx's convention).
type PutOptions = { baseVersion?: string; createOnly?: boolean };
const mockGetNote = vi.fn<(path: string) => Promise<Note>>();
const mockGetLiveNote = vi.fn<(path: string) => Promise<Note>>();
const mockPutNote =
  vi.fn<(path: string, content: string, options?: PutOptions) => Promise<Note>>();
const mockGetBacklinks = vi.fn<(path: string) => Promise<unknown[]>>();
const mockGetVaultSettings = vi.fn<() => Promise<unknown>>();
const mockSetTaskDone =
  vi.fn<(body: SetTaskDoneRequest) => Promise<{ note: Note; task: TaskItem }>>();
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    getNote: (path: string) => mockGetNote(path),
    getLiveNote: (path: string) => mockGetLiveNote(path),
    // Rest args, so an unconditional save is recorded with no options.
    putNote: (...args: [string, string, PutOptions?]) => mockPutNote(...args),
    getBacklinks: (path: string) => mockGetBacklinks(path),
    getVaultSettings: () => mockGetVaultSettings(),
    setTaskDone: (body: SetTaskDoneRequest) => mockSetTaskDone(body),
  };
});

// react-router-dom's useBlocker requires a data router this page doesn't
// need for these tests -- mocked directly (matching NoteBrowser.test.tsx's
// pattern of overriding just the hooks a page uses, keeping everything
// else -- Link, etc. -- actual) so no `<MemoryRouter>` scaffolding is
// needed at all: none of the components rendered here use react-router
// features beyond these three hooks.
const mockNavigate = vi.fn();
const mockUseBlocker =
  vi.fn<
    () => {
      state: "unblocked" | "blocked" | "proceeding";
      proceed?: () => void;
      reset?: () => void;
    }
  >();
vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useParams: () => ({ "*": routePath }),
    useBlocker: () => mockUseBlocker(),
    useSearchParams: () => [searchParams, vi.fn()],
  };
});

// The note route's query string (`?line=N` opens a note at a task).
let searchParams = new URLSearchParams();
// The note open; a test that opens another sets it and re-renders.
let routePath = TEST_PATH;

// A promise settled by the test, for a request still in flight.
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

const mockUseOffline =
  vi.fn<() => { isOffline: boolean; lastSyncedAt: string | null }>();
vi.mock("../context/OfflineContext", () => ({
  useOffline: () => mockUseOffline(),
}));

const mockUseTheme = vi.fn<() => { theme: string; toggleTheme: () => void }>();
vi.mock("../context/ThemeContext", () => ({
  useTheme: () => mockUseTheme(),
}));

const mockUseZenMode = vi.fn<() => { isZen: boolean; toggleZen: () => void }>();
vi.mock("../context/ZenModeContext", () => ({
  useZenMode: () => mockUseZenMode(),
}));

// The editor/preview/header/backlinks children each have their own
// dedicated test files and/or real network calls this page's tests don't
// want to drive -- stubbed to prop-capturing components so this file can
// assert purely on what NoteViewPage itself computes and gates, matching
// MarkdownEditor.test.tsx's established pattern for its own CodeMirror
// dependency.
// biome-ignore lint/suspicious/noExplicitAny: captured props mirror whatever shape NoteViewPage passes.
let capturedEditorProps: any = null;
vi.mock("../components/Editor/MarkdownEditor", () => ({
  MarkdownEditor: (props: unknown) => {
    capturedEditorProps = props;
    return <div data-testid="markdown-editor" />;
  },
}));

// The preview's task checkboxes and open-at-line work across the page and
// the real preview, so tests of those set `realPreview` and get the actual
// component; the rest keep the plain stub.
let realPreview = false;
vi.mock("../components/Editor/MarkdownPreview", async () => {
  const actual = await vi.importActual<
    typeof import("../components/Editor/MarkdownPreview")
  >("../components/Editor/MarkdownPreview");
  return {
    ...actual,
    MarkdownPreview: (props: ComponentProps<typeof actual.MarkdownPreview>) =>
      realPreview ? (
        <div data-testid="markdown-preview">
          <actual.MarkdownPreview {...props} />
        </div>
      ) : (
        <div data-testid="markdown-preview">{props.body}</div>
      ),
  };
});

vi.mock("../lib/mermaid", () => ({ renderMermaid: vi.fn() }));

// biome-ignore lint/suspicious/noExplicitAny: captured props mirror whatever shape NoteViewPage passes.
let capturedHeaderProps: any = null;
vi.mock("../components/Editor/NotePathHeader", () => ({
  NotePathHeader: (props: unknown) => {
    capturedHeaderProps = props;
    return <div data-testid="note-path-header" />;
  },
}));

vi.mock("../components/Backlinks/BacklinksPanel", () => ({
  BacklinksPanel: () => null,
}));

vi.mock("../components/ConfirmDialog/UnsavedChangesDialog", () => ({
  UnsavedChangesDialog: () => null,
}));

import { NoteViewPage } from "./NoteViewPage";

function setOffline(isOffline: boolean, lastSyncedAt: string | null = null) {
  mockUseOffline.mockReturnValue({ isOffline, lastSyncedAt });
}

beforeEach(() => {
  mockGetNote.mockReset();
  mockGetLiveNote.mockReset();
  mockPutNote.mockReset();
  mockGetBacklinks.mockReset();
  mockGetBacklinks.mockResolvedValue([]);
  mockNavigate.mockReset();
  mockUseBlocker.mockReset();
  mockUseBlocker.mockReturnValue({ state: "unblocked" });
  mockUseOffline.mockReset();
  setOffline(false);
  mockUseTheme.mockReset();
  mockUseTheme.mockReturnValue({ theme: "light", toggleTheme: vi.fn() });
  mockUseZenMode.mockReset();
  mockUseZenMode.mockReturnValue({ isZen: false, toggleZen: vi.fn() });
  capturedEditorProps = null;
  capturedHeaderProps = null;
  mockSetTaskDone.mockReset();
  searchParams = new URLSearchParams();
  routePath = TEST_PATH;
  realPreview = false;
  mockGetVaultSettings.mockReset();
  // Never fetched: counts as writable.
  setCachedVaultReadOnly(null);
});

function pressCtrlS() {
  fireEvent.keyDown(window, { key: "s", ctrlKey: true });
}

// Opens the editor and replaces the buffer, as typing would.
async function typeInEditor(text: string) {
  if (!screen.queryByTestId("markdown-editor")) {
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    await screen.findByTestId("markdown-editor");
  }
  act(() => capturedEditorProps.onChange(text));
}

describe("NoteViewPage offline gating", () => {
  it("still saves on Ctrl+S when online (baseline)", async () => {
    mockGetNote.mockResolvedValue(makeNote());
    mockPutNote.mockResolvedValue(makeNote({ content: "Hello again" }));
    setOffline(false);

    render(<NoteViewPage />);
    await screen.findByTestId("markdown-preview");
    await typeInEditor("Hello again");

    pressCtrlS();

    await waitFor(() =>
      expect(mockPutNote).toHaveBeenCalledWith(TEST_PATH, "Hello again", {
        baseVersion: "version-1",
      }),
    );
  });

  it("does not call putNote on Ctrl+S while offline", async () => {
    mockGetNote.mockResolvedValue(makeNote());
    setOffline(true);

    render(<NoteViewPage />);
    await screen.findByTestId("markdown-preview");

    pressCtrlS();

    // Give any accidental async save a turn to fire before asserting its
    // absence.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(mockPutNote).not.toHaveBeenCalled();
  });

  it("disables the Edit button when offline", async () => {
    mockGetNote.mockResolvedValue(makeNote());
    setOffline(true);

    render(<NoteViewPage />);
    await screen.findByTestId("markdown-preview");

    expect(screen.getByRole("button", { name: "Edit" })).toBeDisabled();
  });

  it("leaves the Edit button enabled when online", async () => {
    mockGetNote.mockResolvedValue(makeNote());
    setOffline(false);

    render(<NoteViewPage />);
    await screen.findByTestId("markdown-preview");

    expect(screen.getByRole("button", { name: "Edit" })).toBeEnabled();
  });

  it('shows "This note isn\'t available offline." when getNote rejects while offline', async () => {
    mockGetNote.mockRejectedValue(new Error("network error"));
    setOffline(true);

    render(<NoteViewPage />);

    expect(
      await screen.findByText("This note isn't available offline."),
    ).toBeInTheDocument();
    // The stale/blank content path must not render alongside the error.
    expect(screen.queryByTestId("markdown-preview")).not.toBeInTheDocument();
  });

  it("shows the raw error message when getNote rejects while online", async () => {
    mockGetNote.mockRejectedValue(new Error("boom"));
    setOffline(false);

    render(<NoteViewPage />);

    expect(await screen.findByText("boom")).toBeInTheDocument();
  });

  it("passes readOnly (offline) through to NotePathHeader", async () => {
    mockGetNote.mockResolvedValue(makeNote());
    setOffline(true);

    render(<NoteViewPage />);
    await screen.findByTestId("markdown-preview");

    expect(capturedHeaderProps.readOnly).toBe(true);
  });

  it("freezes the editor read-only in place, without switching back to preview, when a live offline transition happens mid-edit (KTD6)", async () => {
    mockGetNote.mockResolvedValue(makeNote());
    setOffline(false);

    const { rerender } = render(<NoteViewPage />);
    await screen.findByTestId("markdown-preview");

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    await screen.findByTestId("markdown-editor");
    expect(capturedEditorProps.readOnly).toBe(false);

    // Simulate the live `offline` transition OfflineContext would push
    // through on its own -- this component doesn't listen for the event
    // itself, it just re-renders with a new isOffline value.
    setOffline(true);
    rerender(<NoteViewPage />);

    // Still the same editor instance, showing the same draft, just frozen
    // -- not bounced back to preview and not unmounted/navigated away.
    expect(screen.getByTestId("markdown-editor")).toBeInTheDocument();
    expect(screen.queryByTestId("markdown-preview")).not.toBeInTheDocument();
    expect(capturedEditorProps.readOnly).toBe(true);
  });
});

describe("NoteViewPage read-only vault", () => {
  it("hides Edit, the save status and the save shortcut hint, and tells the header", async () => {
    mockGetNote.mockResolvedValue(makeNote());
    setCachedVaultReadOnly(true);

    render(<NoteViewPage />);
    await screen.findByTestId("markdown-preview");

    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.queryByText(/to save/)).toBeNull();
    expect(screen.queryByText("Saved")).toBeNull();
    expect(capturedHeaderProps.readOnly).toBe(true);
  });

  it("makes Ctrl+S a no-op", async () => {
    mockGetNote.mockResolvedValue(makeNote());
    setCachedVaultReadOnly(true);

    render(<NoteViewPage />);
    await screen.findByTestId("markdown-preview");

    const event = new KeyboardEvent("keydown", {
      key: "s",
      ctrlKey: true,
      cancelable: true,
    });
    window.dispatchEvent(event);

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(mockPutNote).not.toHaveBeenCalled();
    // Still swallowed, so the browser's own "Save page" dialog stays shut.
    expect(event.defaultPrevented).toBe(true);
  });

  it("hides Save and freezes the editor when the vault turns out to be read-only mid-edit", async () => {
    mockGetNote.mockResolvedValue(makeNote());

    render(<NoteViewPage />);
    await screen.findByTestId("markdown-preview");
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    await screen.findByTestId("markdown-editor");
    expect(capturedEditorProps.readOnly).toBe(false);
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();

    // The first-visit vault-settings load lands after the user hit Edit.
    mockGetVaultSettings.mockResolvedValue({ read_only: true });
    await act(async () => {
      await loadVaultSettings();
    });

    expect(screen.getByTestId("markdown-editor")).toBeInTheDocument();
    expect(capturedEditorProps.readOnly).toBe(true);
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("keeps Edit visible but disabled when offline on a writable vault", async () => {
    mockGetNote.mockResolvedValue(makeNote());
    setCachedVaultReadOnly(false);
    setOffline(true);

    render(<NoteViewPage />);
    await screen.findByTestId("markdown-preview");

    expect(screen.getByRole("button", { name: "Edit" })).toBeDisabled();
  });
});

describe("NoteViewPage save errors", () => {
  it("renders a 403 from the server as a persistent inline error", async () => {
    mockGetNote.mockResolvedValue(makeNote());
    mockPutNote.mockRejectedValue(new ApiError("This vault is read-only", 403));

    render(<NoteViewPage />);
    await screen.findByTestId("markdown-preview");
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("This vault is read-only");
    // Not a toast: still there later, and the button is usable again.
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(screen.getByRole("alert")).toHaveTextContent("This vault is read-only");
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
  });

  it("clears the inline error once a save succeeds", async () => {
    mockGetNote.mockResolvedValue(makeNote());
    mockPutNote.mockRejectedValueOnce(new ApiError("boom", 500));
    mockPutNote.mockResolvedValueOnce(makeNote());

    render(<NoteViewPage />);
    await screen.findByTestId("markdown-preview");
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("boom");

    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });
});

describe("NoteViewPage guarded save", () => {
  const BASE = "# A\n\nFirst line\nLast line\n";
  const TASK = "- [ ] Water the herbs";

  function lastPutOptions() {
    return mockPutNote.mock.calls.at(-1)?.[2];
  }

  async function openNote(note: Partial<Note> = {}) {
    mockGetNote.mockResolvedValue(makeNote({ content: BASE, ...note }));
    render(<NoteViewPage />);
    await screen.findByTestId("markdown-preview");
  }

  it("sends nothing on Ctrl+S when the buffer is clean", async () => {
    await openNote();
    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    await screen.findByTestId("markdown-editor");

    pressCtrlS();

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(mockPutNote).not.toHaveBeenCalled();
  });

  it("saves with the loaded version, then with the version that save returned", async () => {
    await openNote();
    mockPutNote.mockImplementation(async (_path, content) =>
      makeNote({ content, version: `saved:${content}` }),
    );

    await typeInEditor(`${BASE}One\n`);
    pressCtrlS();
    await waitFor(() => expect(screen.getByText("Saved")).toBeInTheDocument());
    expect(lastPutOptions()).toEqual({ baseVersion: "version-1" });

    await typeInEditor(`${BASE}One\nTwo\n`);
    pressCtrlS();
    await waitFor(() => expect(mockPutNote).toHaveBeenCalledTimes(2));
    // The second save is not refused: it names the file as the first left it.
    expect(lastPutOptions()).toEqual({ baseVersion: `saved:${BASE}One\n` });
    await waitFor(() => expect(screen.getByText("Saved")).toBeInTheDocument());
    expect(mockGetLiveNote).not.toHaveBeenCalled();
  });

  it("saves without a version when the loaded note has none (an old cached copy)", async () => {
    // biome-ignore lint/suspicious/noExplicitAny: a response cached before notes had versions.
    await openNote({ version: undefined as any });
    mockPutNote.mockResolvedValue(makeNote({ content: "Edited\n" }));

    await typeInEditor("Edited\n");
    pressCtrlS();

    await waitFor(() => expect(mockPutNote).toHaveBeenCalledTimes(1));
    expect(lastPutOptions()?.baseVersion).toBeUndefined();
  });

  it("merges a task added elsewhere and saves against the fresh version", async () => {
    await openNote();
    const fresh = makeNote({ content: `${BASE}${TASK}\n`, version: "fresh" });
    const merged = `# A\n\nFirst line, edited\nLast line\n${TASK}\n`;
    mockPutNote
      .mockRejectedValueOnce(new NoteConflictError("The note changed"))
      .mockResolvedValueOnce(makeNote({ content: merged, version: "merged" }));
    mockGetLiveNote.mockResolvedValue(fresh);

    await typeInEditor("# A\n\nFirst line, edited\nLast line\n");
    pressCtrlS();

    await waitFor(() => expect(mockPutNote).toHaveBeenCalledTimes(2));
    expect(mockPutNote.mock.calls[1]).toEqual([
      TEST_PATH,
      merged,
      { baseVersion: "fresh" },
    ]);
    await waitFor(() => expect(capturedEditorProps.value).toBe(merged));
    expect(screen.getByText("Saved")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps the buffer dirty and says so when the refetch comes from the offline cache", async () => {
    await openNote();
    mockPutNote.mockRejectedValue(new NoteConflictError("The note changed"));
    mockGetLiveNote.mockRejectedValue(new CachedNoteError());

    await typeInEditor(`${BASE}Mine\n`);
    pressCtrlS();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Offline -- your changes aren't saved yet.",
    );
    expect(mockPutNote).toHaveBeenCalledTimes(1);
    expect(capturedEditorProps.value).toBe(`${BASE}Mine\n`);
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens the conflict dialog when the merged save is refused too", async () => {
    await openNote();
    mockPutNote.mockRejectedValue(new NoteConflictError("The note changed"));
    mockGetLiveNote.mockResolvedValue(
      makeNote({ content: `${BASE}${TASK}\n`, version: "fresh" }),
    );

    await typeInEditor(`${BASE}Mine\n`);
    pressCtrlS();

    expect(
      await screen.findByRole("dialog", { name: "This note changed" }),
    ).toBeInTheDocument();
    // One automatic merge only.
    expect(mockPutNote).toHaveBeenCalledTimes(2);
    expect(mockGetLiveNote).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
  });

  it("reports a merged save refused for another reason inline, without the dialog", async () => {
    await openNote();
    mockPutNote
      .mockRejectedValueOnce(new NoteConflictError("The note changed"))
      .mockRejectedValueOnce(new ApiError("This vault is read-only", 403));
    mockGetLiveNote.mockResolvedValue(
      makeNote({ content: `${BASE}${TASK}\n`, version: "fresh" }),
    );

    await typeInEditor("# A\n\nFirst line, edited\nLast line\n");
    pressCtrlS();

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This vault is read-only",
    );
    expect(mockPutNote).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(capturedEditorProps.value).toBe("# A\n\nFirst line, edited\nLast line\n");
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
  });

  it("keeps what was typed while a save was in flight, unsaved on the saved base", async () => {
    await openNote();
    const save = deferred<Note>();
    mockPutNote.mockReturnValueOnce(save.promise);

    await typeInEditor(`${BASE}One\n`);
    pressCtrlS();
    await typeInEditor(`${BASE}One\nTwo\n`);
    await act(async () =>
      save.resolve(makeNote({ content: `${BASE}One\n`, version: "saved-1" })),
    );

    expect(capturedEditorProps.value).toBe(`${BASE}One\nTwo\n`);
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();

    mockPutNote.mockResolvedValueOnce(
      makeNote({ content: `${BASE}One\nTwo\n`, version: "saved-2" }),
    );
    pressCtrlS();
    await waitFor(() => expect(mockPutNote).toHaveBeenCalledTimes(2));
    expect(lastPutOptions()).toEqual({ baseVersion: "saved-1" });
    await waitFor(() => expect(screen.getByText("Saved")).toBeInTheDocument());
  });

  it("keeps what was typed while a merged save was in flight, with the merge folded in", async () => {
    await openNote();
    const mine = "# A\n\nFirst line, edited\nLast line\n";
    const merged = `${mine}${TASK}\n`;
    const retry = deferred<Note>();
    mockPutNote
      .mockRejectedValueOnce(new NoteConflictError("The note changed"))
      .mockReturnValueOnce(retry.promise);
    mockGetLiveNote.mockResolvedValue(
      makeNote({ content: `${BASE}${TASK}\n`, version: "fresh" }),
    );

    await typeInEditor(mine);
    pressCtrlS();
    await waitFor(() => expect(mockPutNote).toHaveBeenCalledTimes(2));
    await typeInEditor(`${mine}More\n`);
    await act(async () =>
      retry.resolve(makeNote({ content: merged, version: "merged" })),
    );

    // The task the merge brought in stays, and so does the typing.
    expect(capturedEditorProps.value).toBe(`${mine}More\n${TASK}\n`);
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();

    mockPutNote.mockImplementationOnce(async (_path, content) => makeNote({ content }));
    pressCtrlS();
    await waitFor(() => expect(mockPutNote).toHaveBeenCalledTimes(3));
    expect(lastPutOptions()).toEqual({ baseVersion: "merged" });
  });

  describe("when the note was deleted elsewhere", () => {
    async function saveIntoDeleted() {
      await openNote();
      mockPutNote.mockRejectedValueOnce(new NoteConflictError("The note changed"));
      mockGetLiveNote.mockRejectedValue(new ApiError("Note not found", 404));
      await typeInEditor(`${BASE}Mine\n`);
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
      return screen.findByRole("dialog", { name: "This note was deleted" });
    }

    it("asks, saying the note is gone, instead of failing every save", async () => {
      const dialog = await saveIntoDeleted();

      expect(dialog).toHaveTextContent(/deleted somewhere else/);
      expect(dialog).toHaveTextContent(
        /Keep mine.*saves your version as the note again/,
      );
      // Reloading a note that is gone would only fail.
      expect(within(dialog).queryByRole("button", { name: "Reload" })).toBeNull();
      expect(screen.queryByRole("alert")).toBeNull();
      expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    });

    it("Keep mine saves the note again with an unconditional save", async () => {
      await saveIntoDeleted();
      mockPutNote.mockResolvedValueOnce(
        makeNote({ content: `${BASE}Mine\n`, version: "recreated" }),
      );

      fireEvent.click(screen.getByRole("button", { name: "Keep mine" }));

      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      expect(mockPutNote.mock.calls[1]).toEqual([TEST_PATH, `${BASE}Mine\n`]);
      expect(screen.getByText("Saved")).toBeInTheDocument();
    });
  });

  it("sends the renamed note's version after a rename through the path header", async () => {
    await openNote();
    act(() =>
      capturedHeaderProps.onRenamed(
        makeNote({
          title: "B",
          content: `---\ntitle: B\n---\n${BASE}`,
          version: "renamed",
        }),
      ),
    );
    mockPutNote.mockResolvedValue(makeNote({ version: "saved" }));

    await typeInEditor(`---\ntitle: B\n---\n${BASE}More\n`);
    pressCtrlS();

    await waitFor(() => expect(mockPutNote).toHaveBeenCalledTimes(1));
    expect(lastPutOptions()).toEqual({ baseVersion: "renamed" });
    await waitFor(() => expect(screen.getByText("Saved")).toBeInTheDocument());
  });

  describe("on an overlapping change", () => {
    const MINE = "# A\n\nFirst line, mine\nLast line\n";
    const THEIRS = "# A\n\nFirst line, theirs\nLast line\n";

    async function saveIntoConflict() {
      await openNote();
      mockPutNote.mockRejectedValueOnce(new NoteConflictError("The note changed"));
      mockGetLiveNote.mockResolvedValue(
        makeNote({ content: THEIRS, version: "fresh" }),
      );
      await typeInEditor(MINE);
      fireEvent.click(screen.getByRole("button", { name: "Save" }));
      return screen.findByRole("dialog", { name: "This note changed" });
    }

    it("says what each choice discards and saves nothing yet", async () => {
      const dialog = await saveIntoConflict();

      expect(dialog).toHaveTextContent(/Reload.*discards your unsaved edits/);
      expect(dialog).toHaveTextContent(/Keep mine.*discards the other changes/);
      expect(mockPutNote).toHaveBeenCalledTimes(1);
    });

    it("Reload shows the fresh file and keeps the unsaved text to copy", async () => {
      const writeText = vi.fn<(text: string) => Promise<void>>().mockResolvedValue();
      Object.defineProperty(window.navigator, "clipboard", {
        configurable: true,
        value: { writeText },
      });
      await saveIntoConflict();

      fireEvent.click(screen.getByRole("button", { name: "Reload" }));

      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      expect(capturedEditorProps.value).toBe(THEIRS);
      expect(screen.getByText("Saved")).toBeInTheDocument();
      const copy = screen.getByRole("textbox", { name: "Your unsaved text" });
      expect(copy).toHaveValue(MINE);
      expect(copy).toHaveAttribute("readonly");
      // Nothing was written on the way.
      expect(mockPutNote).toHaveBeenCalledTimes(1);

      fireEvent.click(screen.getByRole("button", { name: "Copy" }));
      await waitFor(() => expect(writeText).toHaveBeenCalledWith(MINE));

      fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
      expect(screen.queryByRole("textbox", { name: "Your unsaved text" })).toBeNull();
    });

    it("Keep mine overwrites with an unconditional save", async () => {
      await saveIntoConflict();
      mockPutNote.mockResolvedValueOnce(makeNote({ content: MINE, version: "kept" }));

      fireEvent.click(screen.getByRole("button", { name: "Keep mine" }));

      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      expect(mockPutNote).toHaveBeenCalledTimes(2);
      expect(mockPutNote.mock.calls[1]).toEqual([TEST_PATH, MINE]);
      expect(capturedEditorProps.value).toBe(MINE);
      expect(screen.getByText("Saved")).toBeInTheDocument();
    });

    it("Reload from the offline cache keeps the dialog open and the buffer", async () => {
      const dialog = await saveIntoConflict();
      mockGetLiveNote.mockRejectedValue(new CachedNoteError());

      fireEvent.click(screen.getByRole("button", { name: "Reload" }));

      expect(await within(dialog).findByRole("alert")).toHaveTextContent(
        "Offline -- your changes aren't saved yet.",
      );
      expect(screen.getByRole("dialog", { name: "This note changed" })).toBe(dialog);
      expect(capturedEditorProps.value).toBe(MINE);
      expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
      expect(screen.queryByRole("textbox", { name: "Your unsaved text" })).toBeNull();
    });

    it("Keep mine that fails says why in the dialog and leaves the buffer unsaved", async () => {
      const dialog = await saveIntoConflict();
      mockPutNote.mockRejectedValueOnce(new ApiError("Disk full", 500));

      fireEvent.click(screen.getByRole("button", { name: "Keep mine" }));

      expect(await within(dialog).findByRole("alert")).toHaveTextContent("Disk full");
      expect(screen.getByRole("dialog", { name: "This note changed" })).toBe(dialog);
      expect(mockPutNote.mock.calls[1]).toEqual([TEST_PATH, MINE]);
      expect(capturedEditorProps.value).toBe(MINE);
      expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    });

    it("Cancel leaves the buffer as it was, unsaved", async () => {
      await saveIntoConflict();

      fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

      expect(screen.queryByRole("dialog")).toBeNull();
      expect(capturedEditorProps.value).toBe(MINE);
      expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
      expect(mockPutNote).toHaveBeenCalledTimes(1);
    });

    it("stays on the note when the save came from the leave-page dialog", async () => {
      const proceed = vi.fn();
      const reset = vi.fn();
      await openNote();
      mockPutNote.mockRejectedValueOnce(new NoteConflictError("The note changed"));
      mockGetLiveNote.mockResolvedValue(
        makeNote({ content: THEIRS, version: "fresh" }),
      );
      // Set before typing, so the re-render the edit causes picks it up.
      mockUseBlocker.mockReturnValue({ state: "blocked", proceed, reset });
      await typeInEditor(MINE);
      // Ctrl+S while blocked goes through the leave-page dialog's Save.
      pressCtrlS();

      expect(
        await screen.findByRole("dialog", { name: "This note changed" }),
      ).toBeInTheDocument();
      expect(proceed).not.toHaveBeenCalled();
      expect(reset).toHaveBeenCalled();
    });
  });

  it("leaves the page after a merged save from the leave-page dialog", async () => {
    const proceed = vi.fn();
    await openNote();
    mockPutNote
      .mockRejectedValueOnce(new NoteConflictError("The note changed"))
      .mockImplementationOnce(async (_path, content) => makeNote({ content }));
    mockGetLiveNote.mockResolvedValue(
      makeNote({ content: `${BASE}${TASK}\n`, version: "fresh" }),
    );
    mockUseBlocker.mockReturnValue({ state: "blocked", proceed, reset: vi.fn() });
    await typeInEditor("# A\n\nFirst line, edited\nLast line\n");

    pressCtrlS();

    await waitFor(() => expect(proceed).toHaveBeenCalled());
    expect(mockPutNote).toHaveBeenCalledTimes(2);
  });
});

describe("NoteViewPage preview tasks", () => {
  // The task is on file line 5: the frontmatter's three lines count.
  const CONTENT = "---\ntitle: A\n---\n# A\n- [ ] Water the herbs\n";
  const TICKED = "---\ntitle: A\n---\n# A\n- [x] Water the herbs ✅ 2026-10-26\n";

  function written(content: string, version: string) {
    const note = makeNote({ content, version });
    const task: TaskItem = {
      path: TEST_PATH,
      title: "A",
      tags: [],
      line: 5,
      text: "Water the herbs",
      done: true,
      done_date: "2026-10-26",
    };
    return { note, task };
  }

  async function openNote(content = CONTENT) {
    realPreview = true;
    mockGetNote.mockResolvedValue(makeNote({ content }));
    const view = render(<NoteViewPage />);
    await screen.findByTestId("markdown-preview");
    return view;
  }

  // Opens note B while note A's tick is still in flight.
  async function openOtherNote(view: ReturnType<typeof render>) {
    routePath = "notes/b.md";
    mockGetNote.mockResolvedValue(
      makeNote({
        path: "notes/b.md",
        content: "# B\n- [ ] Feed the cat\n",
        version: "b-1",
      }),
    );
    view.rerender(<NoteViewPage />);
    await screen.findByRole("checkbox", { name: "Feed the cat" });
  }

  async function expectNoteB() {
    expect(screen.getByRole("checkbox", { name: "Feed the cat" })).toBeInTheDocument();
    expect(screen.queryByText(/Water the herbs/)).toBeNull();
    expect(screen.queryByText(TASK_CHANGED_MESSAGE)).toBeNull();
    expect(screen.getByText("Saved")).toBeInTheDocument();
    // Note B saves against its own version.
    mockPutNote.mockImplementation(async (path, content) =>
      makeNote({ path, content, version: "b-2" }),
    );
    await typeInEditor("# B\n- [ ] Feed the cat\nMore\n");
    pressCtrlS();
    await waitFor(() =>
      expect(mockPutNote).toHaveBeenCalledWith(
        "notes/b.md",
        "# B\n- [ ] Feed the cat\nMore\n",
        { baseVersion: "b-1" },
      ),
    );
  }

  function checkbox() {
    return screen.getByRole("checkbox", { name: "Water the herbs" });
  }

  it("ticks with the file line, frontmatter included, and today's date", async () => {
    await openNote();
    mockSetTaskDone.mockResolvedValue(written(TICKED, "version-2"));

    fireEvent.click(checkbox());

    expect(mockSetTaskDone).toHaveBeenCalledWith({
      path: TEST_PATH,
      line: 5,
      text: "Water the herbs",
      done: true,
      date: localIsoDate(),
    });
    await waitFor(() =>
      expect(
        screen.getByRole("checkbox", { name: "Water the herbs ✅ 2026-10-26" }),
      ).toBeChecked(),
    );
    expect(screen.getByText("Saved")).toBeInTheDocument();
  });

  it("saves the next edit against the version the tick returned", async () => {
    await openNote();
    mockSetTaskDone.mockResolvedValue(written(TICKED, "version-2"));
    fireEvent.click(checkbox());
    await waitFor(() => expect(screen.getAllByRole("checkbox")[0]).toBeChecked());
    mockPutNote.mockImplementation(async (_path, content) =>
      makeNote({ content, version: "version-3" }),
    );

    await typeInEditor(`${TICKED}More\n`);
    pressCtrlS();

    await waitFor(() =>
      expect(mockPutNote).toHaveBeenCalledWith(TEST_PATH, `${TICKED}More\n`, {
        baseVersion: "version-2",
      }),
    );
    await waitFor(() => expect(screen.getByText("Saved")).toBeInTheDocument());
    expect(mockGetLiveNote).not.toHaveBeenCalled();
  });

  it("ignores a tick's answer once another note is open", async () => {
    const view = await openNote();
    const tick = deferred<{ note: Note; task: TaskItem }>();
    mockSetTaskDone.mockReturnValue(tick.promise);
    fireEvent.click(checkbox());

    await openOtherNote(view);
    await act(async () => tick.resolve(written(TICKED, "version-2")));

    await expectNoteB();
  });

  it("ignores a refused tick's reload once another note is open", async () => {
    const view = await openNote();
    const tick = deferred<{ note: Note; task: TaskItem }>();
    mockSetTaskDone.mockReturnValue(tick.promise);
    mockGetLiveNote.mockResolvedValue(
      makeNote({ content: "# A\n- [ ] Moved task\n", version: "version-9" }),
    );
    fireEvent.click(checkbox());

    await openOtherNote(view);
    await act(async () =>
      tick.reject(new ApiError("The note changed since the task was loaded", 409)),
    );

    await expectNoteB();
  });

  it("keeps what was typed while a tick was in flight, with the tick folded in", async () => {
    await openNote();
    const tick = deferred<{ note: Note; task: TaskItem }>();
    mockSetTaskDone.mockReturnValue(tick.promise);
    fireEvent.click(checkbox());

    // A line away from the task's, so the two merge.
    const retitle = (text: string) => text.replace("title: A", "title: Garden");
    await typeInEditor(retitle(CONTENT));
    await act(async () => tick.resolve(written(TICKED, "version-2")));

    expect(capturedEditorProps.value).toBe(retitle(TICKED));
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    mockPutNote.mockImplementation(async (_path, content) =>
      makeNote({ content, version: "version-3" }),
    );
    pressCtrlS();
    await waitFor(() =>
      expect(mockPutNote).toHaveBeenCalledWith(TEST_PATH, retitle(TICKED), {
        baseVersion: "version-2",
      }),
    );
  });

  it("keeps typing on the ticked line as it is, so its save is refused, not lost", async () => {
    await openNote();
    const tick = deferred<{ note: Note; task: TaskItem }>();
    mockSetTaskDone.mockReturnValue(tick.promise);
    fireEvent.click(checkbox());

    const typed = "---\ntitle: A\n---\n# A\n- [ ] Water the herbs and the roses\n";
    await typeInEditor(typed);
    await act(async () => tick.resolve(written(TICKED, "version-2")));

    expect(capturedEditorProps.value).toBe(typed);
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();
    // Saved against the version before the tick, the server refuses it and
    // the conflict dialog asks, rather than the tick being overwritten.
    mockPutNote.mockRejectedValue(new NoteConflictError("The note changed"));
    mockGetLiveNote.mockResolvedValue(
      makeNote({ content: TICKED, version: "version-2" }),
    );
    pressCtrlS();
    expect(
      await screen.findByRole("dialog", { name: "This note changed" }),
    ).toBeInTheDocument();
    expect(mockPutNote.mock.calls[0]).toEqual([
      TEST_PATH,
      typed,
      { baseVersion: "version-1" },
    ]);
  });

  it("disables the checkboxes with a Save first hint while the buffer is dirty", async () => {
    await openNote();
    await typeInEditor(`${CONTENT}\nDraft\n`);
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));

    expect(checkbox()).toBeDisabled();
    expect(checkbox()).toHaveAccessibleDescription(/Save first/);
    fireEvent.click(checkbox());
    expect(mockSetTaskDone).not.toHaveBeenCalled();
  });

  it("disables the checkboxes offline", async () => {
    setOffline(true);
    await openNote();

    expect(checkbox()).toBeDisabled();
  });

  it("renders no enabled checkbox on a read-only vault", async () => {
    setCachedVaultReadOnly(true);
    await openNote();

    expect(checkbox()).toBeDisabled();
    expect(screen.queryByText(/Save first/)).toBeNull();
  });

  it("shows the shared message and reloads the note on a 409", async () => {
    await openNote();
    mockSetTaskDone.mockRejectedValue(
      new ApiError("The note changed since the task was loaded", 409),
    );
    mockGetLiveNote.mockResolvedValue(
      makeNote({ content: "# A\n- [ ] Moved task\n", version: "version-9" }),
    );

    fireEvent.click(checkbox());

    expect(await screen.findByText(TASK_CHANGED_MESSAGE)).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Moved task" })).toBeEnabled();
    expect(mockGetLiveNote).toHaveBeenCalledWith(TEST_PATH);
  });

  it("shows the note's absence when a 404 tick's reload fails too", async () => {
    await openNote();
    mockSetTaskDone.mockRejectedValue(new ApiError("Note not found", 404));
    mockGetLiveNote.mockRejectedValue(new ApiError("Note not found", 404));

    fireEvent.click(checkbox());

    expect(await screen.findByRole("alert")).toHaveTextContent("Note not found");
  });

  it("reports any other failure inline and leaves the note as it was", async () => {
    await openNote();
    mockSetTaskDone.mockRejectedValue(new ApiError("This vault is read-only", 403));

    fireEvent.click(checkbox());

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This vault is read-only",
    );
    expect(checkbox()).not.toBeChecked();
    expect(mockGetLiveNote).not.toHaveBeenCalled();
  });
});

describe("NoteViewPage open at line", () => {
  // Line 7 is the task; line 6 is a heading.
  const CONTENT = "---\ntitle: A\ntags: [x]\n---\n\n# A\n- [ ] Call the plumber\n";
  const scrollIntoView = vi.fn();

  beforeEach(() => {
    scrollIntoView.mockReset();
    Element.prototype.scrollIntoView = scrollIntoView;
  });

  async function openAt(line: string, content = CONTENT) {
    realPreview = true;
    searchParams = new URLSearchParams({ line });
    mockGetNote.mockResolvedValue(makeNote({ content }));
    const view = render(<NoteViewPage />);
    await screen.findByTestId("markdown-preview");
    return view;
  }

  it("scrolls to the task on that line and highlights it for 2 seconds", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { container } = await openAt("7");
      const item = container.querySelector('[data-source-line="7"]');

      await waitFor(() => expect(item).toHaveClass("task-list-item--highlight"));
      expect(scrollIntoView).toHaveBeenCalledTimes(1);
      expect(scrollIntoView.mock.contexts[0]).toBe(item);
      expect(item).toHaveTextContent("The task you opened");

      act(() => vi.advanceTimersByTime(2000));
      expect(item).not.toHaveClass("task-list-item--highlight");
      expect(item).not.toHaveTextContent("The task you opened");
    } finally {
      vi.useRealTimers();
    }
  });

  it("opens at the top with a notice when that line no longer holds a task", async () => {
    const { container } = await openAt("6");

    expect(await screen.findByText(/task has moved/i)).toBeInTheDocument();
    expect(scrollIntoView).not.toHaveBeenCalled();
    expect(container.querySelector(".task-list-item--highlight")).toBeNull();
  });

  it("ignores a line that isn't a number", async () => {
    await openAt("seven");

    expect(screen.queryByText(/task has moved/i)).toBeNull();
    expect(scrollIntoView).not.toHaveBeenCalled();
  });
});

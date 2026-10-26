import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { loadVaultSettings } from "../lib/vaultSettings";
import { setCachedVaultReadOnly } from "../test/factories";
import type { Note } from "../types/note";

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

// Only getNote/putNote/getBacklinks touch the network from this page's
// tree; encodeNotePath/errorMessage are real logic worth exercising as-is
// (matches TasksPage.test.tsx's convention).
const mockGetNote = vi.fn<(path: string) => Promise<Note>>();
const mockPutNote = vi.fn<(path: string, content: string) => Promise<Note>>();
const mockGetBacklinks = vi.fn<(path: string) => Promise<unknown[]>>();
const mockGetVaultSettings = vi.fn<() => Promise<unknown>>();
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    getNote: (path: string) => mockGetNote(path),
    putNote: (path: string, content: string) => mockPutNote(path, content),
    getBacklinks: (path: string) => mockGetBacklinks(path),
    getVaultSettings: () => mockGetVaultSettings(),
  };
});

// react-router-dom's useBlocker requires a data router this page doesn't
// need for these tests -- mocked directly (matching NoteBrowser.test.tsx's
// pattern of overriding just the hooks a page uses, keeping everything
// else -- Link, etc. -- actual) so no `<MemoryRouter>` scaffolding is
// needed at all: none of the components rendered here use react-router
// features beyond these three hooks.
const mockNavigate = vi.fn();
const mockUseBlocker = vi.fn<() => { state: "unblocked" | "blocked" | "proceeding" }>();
vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    useNavigate: () => mockNavigate,
    useParams: () => ({ "*": TEST_PATH }),
    useBlocker: () => mockUseBlocker(),
  };
});

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

vi.mock("../components/Editor/MarkdownPreview", () => ({
  MarkdownPreview: ({ body }: { body: string }) => (
    <div data-testid="markdown-preview">{body}</div>
  ),
}));

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
  mockGetVaultSettings.mockReset();
  // Never fetched: counts as writable.
  setCachedVaultReadOnly(null);
});

function pressCtrlS() {
  fireEvent.keyDown(window, { key: "s", ctrlKey: true });
}

describe("NoteViewPage offline gating", () => {
  it("still saves on Ctrl+S when online (baseline)", async () => {
    mockGetNote.mockResolvedValue(makeNote());
    mockPutNote.mockResolvedValue(makeNote({ content: "Hello world" }));
    setOffline(false);

    render(<NoteViewPage />);
    await screen.findByTestId("markdown-preview");

    pressCtrlS();

    await waitFor(() =>
      expect(mockPutNote).toHaveBeenCalledWith(TEST_PATH, "Hello world"),
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

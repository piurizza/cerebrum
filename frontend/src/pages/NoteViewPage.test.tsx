import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
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
    ...overrides,
  };
}

// Only getNote/putNote/getBacklinks touch the network from this page's
// tree; encodeNotePath/errorMessage are real logic worth exercising as-is
// (matches TasksPage.test.tsx's convention).
const mockGetNote = vi.fn<(path: string) => Promise<Note>>();
const mockPutNote = vi.fn<(path: string, content: string) => Promise<Note>>();
const mockGetBacklinks = vi.fn<(path: string) => Promise<unknown[]>>();
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    getNote: (path: string) => mockGetNote(path),
    putNote: (path: string, content: string) => mockPutNote(path, content),
    getBacklinks: (path: string) => mockGetBacklinks(path),
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

  it("passes isOffline through to NotePathHeader", async () => {
    mockGetNote.mockResolvedValue(makeNote());
    setOffline(true);

    render(<NoteViewPage />);
    await screen.findByTestId("markdown-preview");

    expect(capturedHeaderProps.isOffline).toBe(true);
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

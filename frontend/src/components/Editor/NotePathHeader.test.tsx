import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setCachedVaultReadOnly } from "../../test/factories";

// NotePathHeader reads `notes`/`refreshNotes` from NotesContext (used by
// the rename-path-collision check and the post-mutation refresh) -- these
// tests never enter the rename/delete flow itself, so a minimal stub is
// enough, matching NoteBrowser.test.tsx's mocking pattern for the same
// context.
vi.mock("../../context/NotesContext", () => ({
  useNotes: () => ({ notes: [], refreshNotes: vi.fn() }),
}));

import { NotePathHeader } from "./NotePathHeader";

beforeEach(() => {
  // Never fetched: counts as writable.
  setCachedVaultReadOnly(null);
});

// Regression coverage for review finding #3 (2026-08-31 code review): this
// file did not exist before -- the `disabled={readOnly}` JSX on Rename and
// Delete was never rendered or asserted anywhere in the suite (the only
// prior coverage, in NoteViewPage.test.tsx, mocks this component entirely
// and only checks that the prop value reaches the mock).
describe("NotePathHeader offline gating (R3)", () => {
  const baseProps = {
    path: "notes/example.md",
    title: "Example",
    created: null,
    updated: null,
    onRenamed: vi.fn(),
    onDeleted: vi.fn(),
  };

  it("enables Rename and Delete when online (default)", () => {
    render(<NotePathHeader {...baseProps} />);

    expect(screen.getByRole("button", { name: "Rename" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Delete" })).toBeEnabled();
  });

  it("disables Rename and Delete while offline", () => {
    // NoteViewPage passes `readOnly={!canWrite}`; on a writable vault that
    // is the offline case.
    render(<NotePathHeader {...baseProps} readOnly={true} />);

    expect(screen.getByRole("button", { name: "Rename" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
  });
});

describe("NotePathHeader read-only vault", () => {
  const baseProps = {
    path: "notes/example.md",
    title: "Example",
    created: null,
    updated: null,
    onRenamed: vi.fn(),
    onDeleted: vi.fn(),
  };

  it("hides Rename and Delete, keeping Copy path", () => {
    setCachedVaultReadOnly(true);

    render(<NotePathHeader {...baseProps} readOnly={true} />);

    expect(screen.queryByRole("button", { name: "Rename" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    expect(screen.getByRole("button", { name: "Copy path" })).toBeEnabled();
    expect(screen.getByText("notes/example.md")).toBeInTheDocument();
  });

  it("shows Rename and Delete on a vault known to be writable", () => {
    setCachedVaultReadOnly(false);

    render(<NotePathHeader {...baseProps} readOnly={false} />);

    expect(screen.getByRole("button", { name: "Rename" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Delete" })).toBeEnabled();
  });
});

describe("NotePathHeader rename form", () => {
  it("asks to Confirm the rename, not to Rename again", () => {
    render(
      <NotePathHeader
        path="notes/example.md"
        title="Example"
        created={null}
        updated={null}
        onRenamed={vi.fn()}
        onDeleted={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Rename" }));

    expect(screen.getByRole("button", { name: "Confirm" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Rename" })).toBeNull();
  });
});

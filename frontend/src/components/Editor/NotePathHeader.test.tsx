import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// NotePathHeader reads `notes`/`refreshNotes` from NotesContext (used by
// the rename-path-collision check and the post-mutation refresh) -- these
// tests never enter the rename/delete flow itself, so a minimal stub is
// enough, matching NoteBrowser.test.tsx's mocking pattern for the same
// context.
vi.mock("../../context/NotesContext", () => ({
  useNotes: () => ({ notes: [], refreshNotes: vi.fn() }),
}));

import { NotePathHeader } from "./NotePathHeader";

// Regression coverage for review finding #3 (2026-08-31 code review): this
// file did not exist before -- the `disabled={isOffline}` JSX on Rename and
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
    render(<NotePathHeader {...baseProps} isOffline={true} />);

    expect(screen.getByRole("button", { name: "Rename" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
  });
});

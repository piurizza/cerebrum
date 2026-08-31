import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { UnsavedChangesDialog } from "./UnsavedChangesDialog";

describe("UnsavedChangesDialog", () => {
  it("calls onSave when the Save button is clicked", async () => {
    const user = userEvent.setup();
    const onSave = vi.fn();
    render(
      <UnsavedChangesDialog onSave={onSave} onDiscard={vi.fn()} onCancel={vi.fn()} />,
    );

    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("calls onDiscard when the Discard button is clicked", async () => {
    const user = userEvent.setup();
    const onDiscard = vi.fn();
    render(
      <UnsavedChangesDialog
        onSave={vi.fn()}
        onDiscard={onDiscard}
        onCancel={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Discard" }));

    expect(onDiscard).toHaveBeenCalledTimes(1);
  });

  it("calls onCancel when the Cancel button is clicked", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(
      <UnsavedChangesDialog onSave={vi.fn()} onDiscard={vi.fn()} onCancel={onCancel} />,
    );

    await user.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("disables Save, Discard, Cancel, and the backdrop button when busy", () => {
    render(
      <UnsavedChangesDialog
        busy
        onSave={vi.fn()}
        onDiscard={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Saving..." })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Discard" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Close dialog" })).toBeDisabled();
  });

  it("calls onCancel on Escape when not busy", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(
      <UnsavedChangesDialog onSave={vi.fn()} onDiscard={vi.fn()} onCancel={onCancel} />,
    );

    await user.keyboard("{Escape}");

    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("does not call onCancel on Escape when busy", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    render(
      <UnsavedChangesDialog
        busy
        onSave={vi.fn()}
        onDiscard={vi.fn()}
        onCancel={onCancel}
      />,
    );

    await user.keyboard("{Escape}");

    expect(onCancel).not.toHaveBeenCalled();
  });

  it("renders the error prop as an alert", () => {
    render(
      <UnsavedChangesDialog
        error="Save failed: network error"
        onSave={vi.fn()}
        onDiscard={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent("Save failed: network error");
  });

  // Regression coverage for review finding #8 (2026-08-31 code review):
  // this was the one write entry point in NoteViewPage never gated on
  // isOffline -- Save disables here, but Discard/Cancel (neither touches
  // the network) must stay available so an offline user can still leave
  // the dirty note.
  it("disables only Save, not Discard/Cancel, when isOffline", () => {
    render(
      <UnsavedChangesDialog
        isOffline
        onSave={vi.fn()}
        onDiscard={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Discard" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeEnabled();
  });
});

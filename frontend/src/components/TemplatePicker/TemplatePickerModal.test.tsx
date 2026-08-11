import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { TemplateOption } from "../../lib/templates";
import { TemplatePickerModal } from "./TemplatePickerModal";

const MATCHING: TemplateOption = {
  path: "templates/standup/Standup.md",
  name: "Standup",
  scope: "standup",
  tier: "matching-scope",
};
const GLOBAL: TemplateOption = {
  path: "templates/Meeting.md",
  name: "Meeting",
  scope: null,
  tier: "global",
};
const OTHER: TemplateOption = {
  path: "templates/planning/Weekly.md",
  name: "Weekly",
  scope: "planning",
  tier: "other-scope",
};

function renderModal(
  overrides: Partial<React.ComponentProps<typeof TemplatePickerModal>> = {},
) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(
    <TemplatePickerModal
      title="Choose a template"
      options={[MATCHING, GLOBAL, OTHER]}
      pending={false}
      onConfirm={onConfirm}
      onCancel={onCancel}
      {...overrides}
    />,
  );
  return { onConfirm, onCancel };
}

describe("TemplatePickerModal", () => {
  it("renders Blank note plus every option, with a section label for each populated tier", () => {
    renderModal();

    expect(screen.getByText("Blank note")).toBeInTheDocument();
    expect(screen.getByText("Suggested for this folder")).toBeInTheDocument();
    expect(screen.getByText("Templates")).toBeInTheDocument();
    expect(screen.getByText("Other templates")).toBeInTheDocument();
    expect(screen.getByLabelText("Standup (standup)")).toBeInTheDocument();
    expect(screen.getByLabelText("Meeting")).toBeInTheDocument();
    expect(screen.getByLabelText("Weekly (planning)")).toBeInTheDocument();
  });

  it("omits a tier's section label entirely when that tier has zero options", () => {
    renderModal({ options: [GLOBAL] });

    expect(screen.queryByText("Suggested for this folder")).not.toBeInTheDocument();
    expect(screen.getByText("Templates")).toBeInTheDocument();
    expect(screen.queryByText("Other templates")).not.toBeInTheDocument();
  });

  it("calls onConfirm(null) when confirmed with the default (Blank note) selection", async () => {
    const user = userEvent.setup();
    const { onConfirm } = renderModal();

    await user.click(screen.getByRole("button", { name: "Create note" }));

    expect(onConfirm).toHaveBeenCalledWith(null);
  });

  it("calls onConfirm(path) after selecting a template and confirming", async () => {
    const user = userEvent.setup();
    const { onConfirm } = renderModal();

    await user.click(screen.getByLabelText("Meeting"));
    await user.click(screen.getByRole("button", { name: "Create note" }));

    expect(onConfirm).toHaveBeenCalledWith(GLOBAL.path);
  });

  it("calls onCancel on Cancel-button click and on Escape", async () => {
    const user = userEvent.setup();
    const { onCancel } = renderModal();

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);

    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledTimes(2);
  });

  it("disables Confirm/Cancel and shows Creating… while pending", () => {
    renderModal({ pending: true });

    expect(screen.getByRole("button", { name: "Creating…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  });

  it("does not call onCancel via backdrop click or Escape while pending", async () => {
    // Regression guard: confirming starts an uncancellable
    // fetch-then-write-then-navigate chain, so a "successful" dismiss
    // mid-flight must not be possible via any path -- otherwise the note
    // still gets created and the app still navigates once the chain
    // resolves, despite the user having explicitly backed out.
    const user = userEvent.setup();
    const { onCancel } = renderModal({ pending: true });

    await user.click(screen.getByRole("button", { name: "Close dialog" }));
    await user.keyboard("{Escape}");

    expect(onCancel).not.toHaveBeenCalled();
  });

  it("renders the passed error text", () => {
    renderModal({ error: "network error" });

    expect(screen.getByRole("alert")).toHaveTextContent("network error");
  });

  it("renders without crashing when options is empty", () => {
    renderModal({ options: [] });

    expect(screen.getByText("Blank note")).toBeInTheDocument();
  });
});

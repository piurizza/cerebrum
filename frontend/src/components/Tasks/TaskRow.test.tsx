import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { TaskItem } from "../../types/note";

// The note list wikilinks resolve against -- the real hook needs a
// NotesProvider, which would fetch (matches InlineMarkdown.test.tsx).
vi.mock("../../context/NotesContext", () => ({
  useNotesIfLoaded: () => [
    { path: "garden/herbs.md", title: "herbs", tags: [], created: null, updated: null },
  ],
}));

import { TaskRow } from "./TaskRow";

function makeTask(extra: Partial<TaskItem> = {}): TaskItem {
  return {
    path: "garden/plan.md",
    title: "Garden plan",
    line: 7,
    text: "Water the [[herbs]] **today**",
    tags: [],
    done: false,
    done_date: null,
    ...extra,
  };
}

function renderRow(props: Partial<Parameters<typeof TaskRow>[0]> = {}) {
  const onToggle = vi.fn();
  render(
    <MemoryRouter>
      <ul>
        <TaskRow task={makeTask()} toggle="enabled" onToggle={onToggle} {...props} />
      </ul>
    </MemoryRouter>,
  );
  return { onToggle };
}

describe("TaskRow", () => {
  it("names the checkbox by the task text and ticks it from the keyboard", async () => {
    const user = userEvent.setup();
    const { onToggle } = renderRow();

    const checkbox = screen.getByRole("checkbox", { name: "Water the herbs today" });
    expect(checkbox).not.toBeChecked();
    await user.tab();
    expect(checkbox).toHaveFocus();
    await user.keyboard(" ");

    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("renders the text as inline markdown whose links work apart from the checkbox", async () => {
    const user = userEvent.setup();
    const { onToggle } = renderRow();

    expect(screen.getByText("today").tagName).toBe("STRONG");
    const link = screen.getByRole("link", { name: "herbs" });
    expect(link).toHaveAttribute("href", "/notes/garden/herbs.md");
    await user.click(link);

    expect(onToggle).not.toHaveBeenCalled();
  });

  it("opens the note at the task's line", () => {
    renderRow();

    expect(screen.getByRole("link", { name: "Open" })).toHaveAttribute(
      "href",
      "/notes/garden/plan.md?line=7",
    );
  });

  it("shows a done task ticked, with its done date as a date rather than the marker", () => {
    renderRow({ task: makeTask({ done: true, done_date: "2026-10-26" }) });

    expect(screen.getByRole("checkbox")).toBeChecked();
    const label = screen.getByText((_, element) => element?.tagName === "TIME");
    expect(label).toHaveAttribute("datetime", "2026-10-26");
    expect(label.textContent).toMatch(/2026/);
    expect(document.body.textContent).not.toContain("✅");
  });

  it("disables the checkbox offline and hides it on a read-only vault", () => {
    const { unmount } = render(
      <MemoryRouter>
        <TaskRow task={makeTask()} toggle="disabled" onToggle={() => {}} />
      </MemoryRouter>,
    );
    expect(screen.getByRole("checkbox")).toBeDisabled();
    unmount();

    renderRow({ toggle: "hidden" });
    expect(screen.queryByRole("checkbox")).toBeNull();
    // The rest of the row still shows.
    expect(screen.getByRole("link", { name: "Open" })).toBeInTheDocument();
  });

  it("offers Undo while the row is in its undo window", async () => {
    const user = userEvent.setup();
    const onUndo = vi.fn();
    renderRow({ task: makeTask({ done: true, done_date: "2026-10-26" }), onUndo });

    await user.click(screen.getByRole("button", { name: "Undo" }));

    expect(onUndo).toHaveBeenCalledTimes(1);
  });

  it("flags a row the filters would hide", () => {
    renderRow({ outsideFilters: true });

    expect(screen.getByText("Outside the current filters")).toBeInTheDocument();
  });

  it("names the note when asked, for the done list", () => {
    renderRow({ showNote: true });

    expect(screen.getByText("Garden plan")).toBeInTheDocument();
  });
});

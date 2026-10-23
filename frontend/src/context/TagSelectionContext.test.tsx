import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TagSelectionProvider, useTagSelection } from "./TagSelectionContext";

let selection: ReturnType<typeof useTagSelection> | null = null;

function Consumer() {
  selection = useTagSelection();
  return (
    <div data-testid="chips">
      {selection.chips
        .map((chip) => `${chip.excluded ? "-" : ""}${chip.tag}`)
        .join(",")}
    </div>
  );
}

function renderSelection() {
  render(
    <TagSelectionProvider>
      <Consumer />
    </TagSelectionProvider>,
  );
  const chips = () => screen.getByTestId("chips").textContent;
  const current = () => {
    if (!selection) throw new Error("not rendered");
    return selection;
  };
  return { chips, current };
}

describe("TagSelectionContext", () => {
  it("keeps one chip per tag, whatever the case", () => {
    const { chips, current } = renderSelection();
    act(() => current().addChip("work", false));
    act(() => current().addChip("Work", true));
    expect(chips()).toBe("-Work");
  });

  it("removes a chip by tag, ignoring case", () => {
    const { chips, current } = renderSelection();
    act(() => current().addChip("work", false));
    act(() => current().addChip("home", false));
    act(() => current().removeChip("WORK"));
    expect(chips()).toBe("home");
  });

  it("toggles an include chip on and off", () => {
    const { chips, current } = renderSelection();
    act(() => current().toggleInclude("work"));
    expect(chips()).toBe("work");
    act(() => current().toggleInclude("work"));
    expect(chips()).toBe("");
  });

  it("turns an exclusion into an include when toggled", () => {
    const { chips, current } = renderSelection();
    act(() => current().addChip("archive", true));
    act(() => current().toggleInclude("archive"));
    expect(chips()).toBe("archive");
  });

  it("clears every chip", () => {
    const { chips, current } = renderSelection();
    act(() => current().addChip("a", false));
    act(() => current().addChip("b", true));
    act(() => current().clearChips());
    expect(chips()).toBe("");
  });

  it("throws outside a provider", () => {
    // React logs the thrown render error; the assertion is the throw itself.
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Consumer />)).toThrow(/TagSelectionProvider/);
    spy.mockRestore();
  });
});

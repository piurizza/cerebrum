import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TaskAddBox } from "./TaskAddBox";

describe("TaskAddBox", () => {
  it("sends the typed text, empties the box and keeps focus for the next task", async () => {
    const user = userEvent.setup();
    const onAdd = vi.fn().mockResolvedValue(undefined);
    render(<TaskAddBox onAdd={onAdd} />);

    const input = screen.getByRole("textbox", { name: "New task" });
    await user.type(input, "Order timber for the shed{Enter}");

    expect(onAdd).toHaveBeenCalledWith("Order timber for the shed");
    expect(input).toHaveValue("");
    expect(input).toHaveFocus();

    await user.type(input, "Buy nails");
    await user.click(screen.getByRole("button", { name: "Add" }));
    expect(onAdd).toHaveBeenLastCalledWith("Buy nails");
  });

  it("adds nothing for an empty or whitespace-only entry", async () => {
    const user = userEvent.setup();
    const onAdd = vi.fn().mockResolvedValue(undefined);
    render(<TaskAddBox onAdd={onAdd} />);

    await user.click(screen.getByRole("button", { name: "Add" }));
    await user.type(screen.getByRole("textbox", { name: "New task" }), "   {Enter}");

    expect(onAdd).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps the text and shows the error inline when the add fails", async () => {
    const user = userEvent.setup();
    const onAdd = vi.fn().mockRejectedValue(new Error("Vault is read-only"));
    render(<TaskAddBox onAdd={onAdd} />);

    const input = screen.getByRole("textbox", { name: "New task" });
    await user.type(input, "Buy seed potatoes{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The task wasn't added: Vault is read-only",
    );
    expect(input).toHaveValue("Buy seed potatoes");
    expect(input).toHaveFocus();

    // Typing again clears the stale error.
    await user.type(input, "!");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("disables the box and its button when told to", () => {
    render(<TaskAddBox onAdd={vi.fn()} disabled />);

    expect(screen.getByRole("textbox", { name: "New task" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
  });
});

import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { UnsavedTextPanel } from "./SaveConflictDialog";

function stubClipboard(writeText: (text: string) => Promise<void>) {
  Object.defineProperty(window.navigator, "clipboard", {
    configurable: true,
    value: { writeText },
  });
}

afterEach(() => {
  Object.defineProperty(window.navigator, "clipboard", {
    configurable: true,
    value: undefined,
  });
});

describe("UnsavedTextPanel", () => {
  it("says Copied once the text is on the clipboard", async () => {
    const writeText = vi.fn<(text: string) => Promise<void>>().mockResolvedValue();
    stubClipboard(writeText);
    render(<UnsavedTextPanel text="Mine" onDismiss={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Copy" }));

    expect(await screen.findByRole("button", { name: "Copied!" })).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith("Mine");
  });

  it("points to the text itself when the clipboard refuses", async () => {
    stubClipboard(
      vi.fn().mockRejectedValue(new DOMException("Denied", "NotAllowedError")),
    );
    render(<UnsavedTextPanel text="Mine" onDismiss={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Copy" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Couldn't copy/);
    expect(screen.getByRole("button", { name: "Copy" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Your unsaved text" })).toHaveValue(
      "Mine",
    );
  });

  it("points to the text itself where there is no clipboard (plain http)", async () => {
    render(<UnsavedTextPanel text="Mine" onDismiss={vi.fn()} />);

    fireEvent.click(screen.getByRole("button", { name: "Copy" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Couldn't copy/);
  });
});

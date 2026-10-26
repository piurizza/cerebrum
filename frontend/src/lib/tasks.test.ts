// @vitest-environment node
// Pure functions, no DOM -- skip jsdom's window/document bootstrap cost.
import { describe, expect, it } from "vitest";
import { ApiError, NoteConflictError } from "../api/client";
import { isTaskChangedError, taskOnLine } from "./tasks";

describe("taskOnLine", () => {
  const content =
    "---\ntitle: A\n---\n- [ ] Open one\nText\n  * [X] Done ✅ 2026-10-20 ^b  \n";

  it("reads the task on a 1-based file line, frontmatter included", () => {
    expect(taskOnLine(content, 4)).toEqual({ checked: false, text: "Open one" });
  });

  it("keeps the done marker and block id in the text, trailing space removed", () => {
    expect(taskOnLine(content, 6)).toEqual({
      checked: true,
      text: "Done ✅ 2026-10-20 ^b",
    });
  });

  it("keeps a line separator in the text: only \\n ends a line", () => {
    expect(taskOnLine("- [ ] One\u2028still one\n", 1)).toEqual({
      checked: false,
      text: "One\u2028still one",
    });
  });

  it("drops a carriage return that belongs to the line", () => {
    expect(taskOnLine("- [ ] Milk\r\n", 1)).toEqual({ checked: false, text: "Milk" });
  });

  it("is null for a line that isn't a task, or isn't there", () => {
    expect(taskOnLine(content, 5)).toBeNull();
    expect(taskOnLine(content, 0)).toBeNull();
    expect(taskOnLine(content, 99)).toBeNull();
    expect(taskOnLine("1. [ ] Numbered\n", 1)).toBeNull();
  });
});

describe("isTaskChangedError", () => {
  it("is true for a 409 (the line changed) and a 404 (the note is gone)", () => {
    expect(isTaskChangedError(new ApiError("changed", 409))).toBe(true);
    expect(isTaskChangedError(new ApiError("Note not found", 404))).toBe(true);
  });

  it("is false for any other failure", () => {
    expect(isTaskChangedError(new ApiError("read-only", 403))).toBe(false);
    expect(isTaskChangedError(new NoteConflictError("changed"))).toBe(false);
    expect(isTaskChangedError(new Error("network"))).toBe(false);
  });
});

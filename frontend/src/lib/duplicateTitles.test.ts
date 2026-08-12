// @vitest-environment node
// Pure function, no DOM -- skip jsdom's window/document bootstrap cost.
import { describe, expect, it } from "vitest";
import { findDuplicateTitles } from "./duplicateTitles";

describe("findDuplicateTitles", () => {
  it("returns an empty set when every title is unique", () => {
    const items = [{ title: "A" }, { title: "B" }];
    expect(findDuplicateTitles(items, (item) => item.title)).toEqual(new Set());
  });

  it("returns titles that occur more than once", () => {
    const items = [{ title: "A" }, { title: "B" }, { title: "A" }];
    expect(findDuplicateTitles(items, (item) => item.title)).toEqual(new Set(["A"]));
  });

  it("returns an empty set for an empty list", () => {
    expect(findDuplicateTitles([], (item: { title: string }) => item.title)).toEqual(
      new Set(),
    );
  });
});

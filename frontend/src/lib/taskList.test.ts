// @vitest-environment node
// Pure functions, no DOM -- skip jsdom's window/document bootstrap cost.
import { describe, expect, it } from "vitest";
import type { TaskItem } from "../types/note";
import {
  byDoneDateDesc,
  byPathAndLine,
  describeTaskFilters,
  doneListSince,
  hasActiveFilters,
  NO_FILTERS,
  taskFilter,
  taskFolders,
} from "./taskList";

function task(path: string, text = "Water the herbs", extra: Partial<TaskItem> = {}) {
  return {
    path,
    title: path,
    line: 1,
    text,
    tags: [],
    done: false,
    done_date: null,
    ...extra,
  } satisfies TaskItem;
}

describe("taskFolders", () => {
  it("lists every folder holding a task and the folders above it, sorted", () => {
    expect(
      taskFolders([
        task("work/clients/acme.md"),
        task("home/garden.md"),
        task("inbox.md"),
        task("home/garden.md"),
      ]),
    ).toEqual(["home", "work", "work/clients"]);
  });
});

describe("taskFilter", () => {
  it("keeps everything when no filter is set", () => {
    expect(taskFilter(NO_FILTERS)(task("a.md"))).toBe(true);
  });

  it("matches the shared tag selection against the note's tags", () => {
    const garden = task("a.md", "Rake", { tags: ["garden/veg"] });
    const untagged = task("b.md");
    const matches = taskFilter({
      ...NO_FILTERS,
      chips: [{ tag: "garden", excluded: false }],
    });
    expect(matches(garden)).toBe(true);
    expect(matches(untagged)).toBe(false);
  });

  it("includes a folder's subfolders, but not a folder that only starts the same", () => {
    const matches = taskFilter({ ...NO_FILTERS, folder: "work" });
    expect(matches(task("work/a.md"))).toBe(true);
    expect(matches(task("work/clients/acme.md"))).toBe(true);
    expect(matches(task("workshop/a.md"))).toBe(false);
    expect(matches(task("a.md"))).toBe(false);
  });

  it("needs every word of the word filter in the text, in any case and order", () => {
    const timber = task("a.md", "Order **timber** for the Shed");
    expect(taskFilter({ ...NO_FILTERS, words: "shed timber" })(timber)).toBe(true);
    expect(taskFilter({ ...NO_FILTERS, words: "  tim  " })(timber)).toBe(true);
    expect(taskFilter({ ...NO_FILTERS, words: "shed nails" })(timber)).toBe(false);
  });
});

describe("hasActiveFilters and describeTaskFilters", () => {
  it("names each active filter", () => {
    const filters = {
      chips: [
        { tag: "garden", excluded: false },
        { tag: "archive", excluded: true },
      ],
      folder: "home",
      words: " seed  potatoes ",
    };
    expect(hasActiveFilters(filters)).toBe(true);
    expect(describeTaskFilters(filters)).toBe(
      "#garden -#archive, folder home, “seed potatoes”",
    );
  });

  it("counts blank words as no filter", () => {
    expect(hasActiveFilters({ ...NO_FILTERS, words: "   " })).toBe(false);
  });
});

describe("ordering", () => {
  it("orders the open list by note path, then line", () => {
    const tasks = [
      task("b.md", "x", { line: 1 }),
      task("a.md", "y", { line: 9 }),
      task("a.md", "z", { line: 2 }),
    ];
    expect([...tasks].sort(byPathAndLine).map((t) => `${t.path}:${t.line}`)).toEqual([
      "a.md:2",
      "a.md:9",
      "b.md:1",
    ]);
  });

  it("orders the done list newest first, then by note path and line", () => {
    const tasks = [
      task("a.md", "old", { line: 1, done: true, done_date: "2026-10-20" }),
      task("b.md", "new b", { line: 1, done: true, done_date: "2026-10-26" }),
      task("a.md", "new a", { line: 4, done: true, done_date: "2026-10-26" }),
    ];
    expect([...tasks].sort(byDoneDateDesc).map((t) => t.text)).toEqual([
      "new a",
      "new b",
      "old",
    ]);
  });
});

describe("doneListSince", () => {
  it("is today and the 13 days before it, across a month boundary", () => {
    expect(doneListSince(new Date(2026, 9, 26))).toBe("2026-10-13");
    expect(doneListSince(new Date(2026, 10, 3))).toBe("2026-10-21");
  });
});

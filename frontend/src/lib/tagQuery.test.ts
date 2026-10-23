// @vitest-environment node
/// <reference types="node" />
// Pure functions, no DOM. Reads the cases file shared with the backend at
// runtime rather than importing it, so the app build never depends on a
// file outside `frontend/`.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { makeNoteMeta } from "../test/factories";
import type { NoteMeta } from "../types/note";
import {
  collectTagCounts,
  hasWords,
  noteMatchesTags,
  parseQueryText,
  serializeQuery,
  suggestTags,
  type TagChip,
  tagFragmentAt,
  tagMatches,
} from "./tagQuery";

interface SharedCases {
  parse: {
    name: string;
    query: string;
    text: string;
    include: string[];
    exclude: string[];
  }[];
  match: { name: string; note: string; query: string; expected: boolean }[];
}

const cases = JSON.parse(
  readFileSync(new URL("../../../fixtures/tag-query.json", import.meta.url), "utf-8"),
) as SharedCases;

function tagged(path: string, ...tags: string[]): NoteMeta {
  return { ...makeNoteMeta(path), tags };
}

const include = (tag: string): TagChip => ({ tag, excluded: false });
const exclude = (tag: string): TagChip => ({ tag, excluded: true });

describe("shared tag query cases", () => {
  it.each(cases.parse.map((c) => [c.name, c] as const))("parses %s", (_, c) => {
    expect(parseQueryText(c.query)).toEqual({
      text: c.text,
      include: c.include,
      exclude: c.exclude,
    });
  });

  it.each(cases.match.map((c) => [c.name, c] as const))("matches %s", (_, c) => {
    expect(tagMatches(c.note, c.query)).toBe(c.expected);
  });
});

describe("hasWords", () => {
  it("counts accented and non-Latin letters as words", () => {
    expect(hasWords("città")).toBe(true);
    expect(hasWords("привет")).toBe(true);
    expect(hasWords("42")).toBe(true);
  });

  it("ignores whitespace and punctuation", () => {
    expect(hasWords("   ")).toBe(false);
    expect(hasWords("# -")).toBe(false);
  });
});

describe("noteMatchesTags", () => {
  it("needs every included tag and none of the excluded ones", () => {
    const chips = [include("a"), include("B"), exclude("c")];
    expect(noteMatchesTags(["a", "b/x"], chips)).toBe(true);
    expect(noteMatchesTags(["a"], chips)).toBe(false);
    expect(noteMatchesTags(["a", "b", "c/old"], chips)).toBe(false);
  });

  it("matches every note when there are no chips", () => {
    expect(noteMatchesTags([], [])).toBe(true);
  });
});

describe("collectTagCounts", () => {
  it("groups spellings case-insensitively and keeps the most used one", () => {
    const notes = [
      tagged("1.md", "Work"),
      tagged("2.md", "Work"),
      tagged("3.md", "Work"),
      tagged("4.md", "work"),
    ];
    expect(collectTagCounts(notes, [])).toEqual([
      { key: "work", tag: "Work", count: 4, parent: null },
    ]);
  });

  it("adds a parent for nested tags, counting its children", () => {
    const counts = collectTagCounts(
      [tagged("1.md", "Work/acme"), tagged("2.md", "home")],
      [],
    );
    expect(counts).toEqual([
      { key: "home", tag: "home", count: 1, parent: null },
      { key: "work", tag: "Work", count: 1, parent: null },
      { key: "work/acme", tag: "Work/acme", count: 1, parent: "work" },
    ]);
  });

  it("counts a note once even when two of its tags share a parent", () => {
    const counts = collectTagCounts([tagged("1.md", "work/a", "work/b")], []);
    expect(counts.find((entry) => entry.key === "work")?.count).toBe(1);
  });

  it("counts only within the notes the current chips match", () => {
    const notes = [tagged("1.md", "a", "b"), tagged("2.md", "a"), tagged("3.md", "c")];
    const counts = collectTagCounts(notes, [include("a")]);
    expect(counts.map(({ key, count }) => [key, count])).toEqual([
      ["a", 2],
      ["b", 1],
      ["c", 0],
    ]);
  });
});

describe("suggestTags", () => {
  const counts = collectTagCounts(
    [
      tagged("1.md", "homework"),
      tagged("2.md", "homework"),
      tagged("3.md", "work"),
      tagged("4.md", "travel"),
    ],
    [],
  );

  it("puts prefix matches before other matches", () => {
    expect(suggestTags(counts, "wo", []).map((entry) => entry.key)).toEqual([
      "work",
      "homework",
    ]);
  });

  it("lists the most used tags for an empty fragment", () => {
    expect(suggestTags(counts, "", []).map((entry) => entry.key)).toEqual([
      "homework",
      "travel",
      "work",
    ]);
  });

  it("leaves out tags already chosen, either way", () => {
    expect(
      suggestTags(counts, "", [include("Work"), exclude("travel")]).map(
        (entry) => entry.key,
      ),
    ).toEqual(["homework"]);
  });

  it("leaves out tags that would give no results", () => {
    const narrowed = collectTagCounts(
      [tagged("1.md", "a", "b"), tagged("2.md", "c")],
      [include("a")],
    );
    expect(suggestTags(narrowed, "", [include("a")]).map((entry) => entry.key)).toEqual(
      ["b"],
    );
  });

  it("shows at most eight", () => {
    const many = collectTagCounts(
      Array.from({ length: 12 }, (_, i) => tagged(`${i}.md`, `tag${i}`)),
      [],
    );
    expect(suggestTags(many, "tag", [])).toHaveLength(8);
  });
});

describe("serializeQuery", () => {
  it("puts the chips before the text, quoting a tag with a space", () => {
    expect(serializeQuery("città", [include("two words"), exclude("old")])).toBe(
      '#"two words" -#old città',
    );
  });

  it("round-trips through parseQueryText", () => {
    expect(
      parseQueryText(serializeQuery("bread", [include("A/b"), exclude("x")])),
    ).toEqual({
      text: "bread",
      include: ["a/b"],
      exclude: ["x"],
    });
  });

  it("sends only the chips when there is no text", () => {
    expect(serializeQuery("  ", [include("work")])).toBe("#work");
  });
});

describe("tagFragmentAt", () => {
  it("finds the tag being typed at the caret", () => {
    expect(tagFragmentAt("bread #wo", 9)).toEqual({
      start: 6,
      end: 9,
      fragment: "wo",
      excluded: false,
    });
  });

  it("marks an exclusion", () => {
    expect(tagFragmentAt("-#ar", 4)).toEqual({
      start: 0,
      end: 4,
      fragment: "ar",
      excluded: true,
    });
  });

  it("finds a bare # as an empty fragment", () => {
    expect(tagFragmentAt("#", 1)).toEqual({
      start: 0,
      end: 1,
      fragment: "",
      excluded: false,
    });
  });

  it("finds a quoted fragment with a space", () => {
    expect(tagFragmentAt('#"two wo', 8)?.fragment).toBe("two wo");
  });

  it("finds nothing outside a tag", () => {
    expect(tagFragmentAt("bread", 5)).toBeNull();
    expect(tagFragmentAt("pre#fi", 6)).toBeNull();
    expect(tagFragmentAt("#work bread", 11)).toBeNull();
  });

  it("finds nothing when the caret is in the middle of a token", () => {
    expect(tagFragmentAt("#work", 3)).toBeNull();
  });
});

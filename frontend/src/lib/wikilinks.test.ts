// @vitest-environment node
/// <reference types="node" />
// Pure functions, no DOM. Reads the cases file shared with the backend at
// runtime rather than importing it, so the app build never depends on a
// file outside `frontend/`.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { closestPath, findWikilinks, NoteLookup } from "./wikilinks";

interface SharedCases {
  parse: {
    name: string;
    text: string;
    expected: Pick<
      ReturnType<typeof findWikilinks>[number],
      "embed" | "target" | "heading" | "alias"
    >[];
  }[];
  resolve: {
    name: string;
    notes: string[];
    source: string;
    target: string;
    expected: string | null;
  }[];
  shortest: { name: string; notes: string[]; path: string; expected: string }[];
}

const cases = JSON.parse(
  readFileSync(
    new URL("../../../fixtures/wikilink-resolution.json", import.meta.url),
    "utf-8",
  ),
) as SharedCases;

describe("shared wikilink cases", () => {
  it.each(cases.parse.map((c) => [c.name, c] as const))("parses %s", (_, c) => {
    const found = findWikilinks(c.text).map(({ embed, target, heading, alias }) => ({
      embed,
      target,
      heading,
      alias,
    }));
    expect(found).toEqual(c.expected);
  });

  it.each(cases.resolve.map((c) => [c.name, c] as const))("resolves %s", (_, c) => {
    expect(new NoteLookup(c.notes).resolve(c.source, c.target)).toBe(c.expected);
  });

  it.each(cases.shortest.map((c) => [c.name, c] as const))(
    "finds the shortest target: %s",
    (_, c) => {
      const lookup = new NoteLookup(c.notes);
      const target = lookup.shortestUnambiguousTarget(c.path);
      expect(target).toBe(c.expected);
      for (const source of [...c.notes, "elsewhere/Source.md"]) {
        expect(lookup.resolve(source, target)).toBe(c.path);
      }
    },
  );
});

describe("findWikilinks", () => {
  it("records where each link is", () => {
    const text = "x ![[Note#H|alias]] y";
    const [link] = findWikilinks(text);
    expect(text.slice(link.start, link.end)).toBe("![[Note#H|alias]]");
  });
});

describe("closestPath", () => {
  it("picks the same folder, then the shortest path, then alphabetical", () => {
    expect(closestPath(["cat.png", "notes/cat.png"], "notes/a.md")).toBe(
      "notes/cat.png",
    );
    expect(closestPath(["deep/er/cat.png", "x/cat.png"], "a.md")).toBe("x/cat.png");
    expect(closestPath(["b/cat.png", "a/cat.png"], "a.md")).toBe("a/cat.png");
  });
});

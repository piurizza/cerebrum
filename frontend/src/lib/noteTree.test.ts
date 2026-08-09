// @vitest-environment node
// Pure functions, no DOM -- skip jsdom's window/document bootstrap cost.
import { describe, expect, it } from "vitest";
import { makeNoteMeta } from "../test/factories";
import {
  buildNoteTree,
  childFolderNames,
  collectFolderPaths,
  joinNotePath,
  splitNotePath,
} from "./noteTree";

describe("splitNotePath / joinNotePath", () => {
  it("are inverses for a nested path", () => {
    const path = "a/b/c.md";
    const { folder, filename } = splitNotePath(path);
    expect(folder).toBe("a/b");
    expect(filename).toBe("c.md");
    expect(joinNotePath(folder, filename)).toBe(path);
  });

  it("are inverses for a root-level path with no folder", () => {
    const path = "c.md";
    const { folder, filename } = splitNotePath(path);
    expect(folder).toBe("");
    expect(filename).toBe("c.md");
    expect(joinNotePath(folder, filename)).toBe(path);
  });
});

describe("collectFolderPaths", () => {
  it("returns every ancestor folder for a deeply nested note path", () => {
    const notes = [makeNoteMeta("a/b/c/note.md")];
    expect(collectFolderPaths(notes)).toEqual(["a", "a/b", "a/b/c"]);
  });

  it("returns no folders for a root-level note", () => {
    expect(collectFolderPaths([makeNoteMeta("note.md")])).toEqual([]);
  });
});

describe("childFolderNames", () => {
  it("returns only the direct child folder names of a given parent", () => {
    const allFolders = ["a", "a/b", "a/b/c", "a/d"];
    expect(childFolderNames(allFolders, "a")).toEqual(["b", "d"]);
  });

  it("returns top-level folder names when parent is the root", () => {
    const allFolders = ["a", "a/b", "x"];
    expect(childFolderNames(allFolders, "")).toEqual(["a", "x"]);
  });
});

describe("buildNoteTree", () => {
  it("groups notes under shared folders and sorts folders before notes alphabetically", () => {
    const notes = [
      makeNoteMeta("root-b.md"),
      makeNoteMeta("root-a.md"),
      makeNoteMeta("zeta/z.md"),
      makeNoteMeta("alpha/b.md"),
      makeNoteMeta("alpha/a.md"),
      makeNoteMeta("alpha/nested/deep.md"),
    ];

    const tree = buildNoteTree(notes);

    // Folders sort before notes at the top level, alphabetically among
    // themselves, with root-level notes alphabetized by title after them.
    expect(tree.map((n) => (n.type === "folder" ? n.name : n.note.path))).toEqual([
      "alpha",
      "zeta",
      "root-a.md",
      "root-b.md",
    ]);

    const alpha = tree[0];
    if (alpha.type !== "folder") throw new Error("expected folder");
    // Within "alpha": the "nested" subfolder sorts before its notes.
    expect(
      alpha.children.map((n) => (n.type === "folder" ? n.name : n.note.path)),
    ).toEqual(["nested", "alpha/a.md", "alpha/b.md"]);

    const nested = alpha.children[0];
    if (nested.type !== "folder") throw new Error("expected folder");
    expect(nested.folderPath).toBe("alpha/nested");
    expect(nested.children).toHaveLength(1);
    expect(nested.children[0]).toEqual({
      type: "note",
      note: notes.find((n) => n.path === "alpha/nested/deep.md"),
    });
  });
});

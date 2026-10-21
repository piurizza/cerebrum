import { type Completion, CompletionContext } from "@codemirror/autocomplete";
import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { afterEach, describe, expect, it } from "vitest";
import { resetVaultFoldersForTests, VAULT_SETTINGS_KEY } from "../../lib/vaultSettings";
import { makeNoteMeta } from "../../test/factories";
import type { NoteMeta } from "../../types/note";
import { noteLinkCompletionSource } from "./noteLinkCompletion";

// Builds a `CompletionContext` against a real `EditorState` whose doc
// already contains the trigger text typed at the end, so
// `context.matchBefore` (called internally by `noteLinkCompletionSource`)
// sees the same text a real user's keystrokes would have produced.
function contextFor(doc: string) {
  const state = EditorState.create({ doc });
  return new CompletionContext(state, doc.length, false);
}

// `Completion.apply` is typed `string | ((view, completion, from, to) =>
// void) | undefined` by CodeMirror -- `noteLinkCompletionSource`'s own
// options always build it as a function (see noteLinkCompletion.ts), so
// this narrows that for the call sites below rather than re-deriving the
// union check in every test.
function applyCompletion(
  option: Completion | undefined,
  view: EditorView,
  from: number,
  to: number,
): void {
  const apply = option?.apply;
  if (typeof apply !== "function") {
    throw new Error("expected option.apply to be a function");
  }
  apply(view, option as Completion, from, to);
}

const manyNotes: NoteMeta[] = [
  makeNoteMeta("notes/apple.md", "Apple"),
  makeNoteMeta("notes/banana.md", "Banana"),
  makeNoteMeta("notes/cherry.md", "Cherry"),
  makeNoteMeta("notes/date.md", "Date"),
  makeNoteMeta("notes/elderberry.md", "Elderberry"),
];

describe("noteLinkCompletionSource", () => {
  it("returns null when there is no [[ trigger before the cursor", () => {
    const source = noteLinkCompletionSource(manyNotes, "notes/current.md");
    const result = source(contextFor("just some text"));
    expect(result).toBeNull();
  });

  it("returns candidates sorted by title, capped at 20 results", () => {
    const lots: NoteMeta[] = Array.from({ length: 25 }, (_, i) =>
      makeNoteMeta(`notes/n${i}.md`, `Note ${String(25 - i).padStart(2, "0")}`),
    );
    const source = noteLinkCompletionSource(lots, "notes/current.md");

    const result = source(contextFor("[["));

    expect(result).not.toBeNull();
    expect(result?.options).toHaveLength(20);
    const titles = result?.options.map((o) => o.label) ?? [];
    expect(titles).toEqual([...titles].sort((a, b) => a.localeCompare(b)));
  });

  it("filters candidates by title or path, case-insensitively", () => {
    const source = noteLinkCompletionSource(manyNotes, "notes/current.md");

    const byTitle = source(contextFor("[[ban"));
    expect(byTitle?.options.map((o) => o.label)).toEqual(["Banana"]);

    const byTitleUpper = source(contextFor("[[BAN"));
    expect(byTitleUpper?.options.map((o) => o.label)).toEqual(["Banana"]);

    const byPath = source(contextFor("[[cherry.md"));
    expect(byPath?.options.map((o) => o.label)).toEqual(["Cherry"]);

    const noMatch = source(contextFor("[[zzz"));
    expect(noMatch).toBeNull();
  });

  it("excludes the note currently being edited from its own candidate list", () => {
    const source = noteLinkCompletionSource(manyNotes, "notes/apple.md");

    const result = source(contextFor("[[a"));

    expect(result?.options.map((o) => o.label)).not.toContain("Apple");
  });

  it("accepting a completion inserts a standard markdown link with a relative path", () => {
    const source = noteLinkCompletionSource(manyNotes, "notes/sub/current.md");
    const doc = "[[ban";
    const result = source(contextFor(doc));
    expect(result).not.toBeNull();

    const view = new EditorView({
      state: EditorState.create({ doc }),
      parent: document.createElement("div"),
    });
    try {
      const option = result?.options.find((o) => o.label === "Banana");
      expect(option?.apply).toBeTypeOf("function");

      applyCompletion(option, view, result?.from ?? 0, doc.length);

      expect(view.state.doc.toString()).toBe("[Banana](../banana.md)");
    } finally {
      view.destroy();
    }
  });

  it("consumes a trailing ]] instead of leaving it behind", () => {
    const source = noteLinkCompletionSource(manyNotes, "notes/current.md");
    const doc = "[[ban]]";
    // Cursor sits right after "ban", before the closing brackets -- matching
    // how the user would still be mid-typing the query when they accept.
    const cursorPos = "[[ban".length;
    const state = EditorState.create({ doc });
    const context = new CompletionContext(state, cursorPos, false);
    const result = source(context);
    expect(result).not.toBeNull();

    const view = new EditorView({ state, parent: document.createElement("div") });
    try {
      const option = result?.options.find((o) => o.label === "Banana");

      applyCompletion(option, view, result?.from ?? 0, cursorPos);

      expect(view.state.doc.toString()).toBe("[Banana](banana.md)");
    } finally {
      view.destroy();
    }
  });

  describe("in wikilink mode", () => {
    function useLinkFormat(linkFormat: string) {
      window.localStorage.setItem(
        VAULT_SETTINGS_KEY,
        JSON.stringify({ link_format: linkFormat }),
      );
      resetVaultFoldersForTests();
    }

    afterEach(() => {
      window.localStorage.clear();
      resetVaultFoldersForTests();
    });

    function pick(notes: NoteMeta[], label: string, doc = "[[") {
      const source = noteLinkCompletionSource(notes, "notes/current.md");
      const state = EditorState.create({ doc });
      const result = source(new CompletionContext(state, 2, false));
      const view = new EditorView({ state, parent: document.createElement("div") });
      try {
        const option = result?.options.find((o) => o.label === label);
        applyCompletion(option, view, result?.from ?? 0, 2);
        return view.state.doc.toString();
      } finally {
        view.destroy();
      }
    }

    it("inserts [[name]] when the title is the file name", () => {
      useLinkFormat("wikilink");
      expect(pick([makeNoteMeta("notes/My Note.md", "My Note")], "My Note")).toBe(
        "[[My Note]]",
      );
    });

    it("adds the title as an alias when it differs from the file name", () => {
      useLinkFormat("wikilink");
      expect(pick([makeNoteMeta("notes/my-note.md", "My Note")], "My Note")).toBe(
        "[[my-note|My Note]]",
      );
    });

    it("adds the folder when another note shares the file name", () => {
      useLinkFormat("wikilink");
      const notes = [
        makeNoteMeta("a/Note.md", "Note A"),
        makeNoteMeta("b/Note.md", "Note B"),
      ];
      expect(pick(notes, "Note A")).toBe("[[a/Note|Note A]]");
    });

    it("consumes a trailing ]]", () => {
      useLinkFormat("wikilink");
      expect(pick([makeNoteMeta("B.md", "B")], "B", "[[]]")).toBe("[[B]]");
    });

    it("leaves out a title that can't be an alias", () => {
      useLinkFormat("wikilink");
      expect(pick([makeNoteMeta("draft.md", "Plan [v2]")], "Plan [v2]")).toBe(
        "[[draft]]",
      );
    });

    it("falls back to a markdown link for a file name a wikilink can't hold", () => {
      useLinkFormat("wikilink");
      expect(pick([makeNoteMeta("notes/a|b.md", "A or B")], "A or B")).toBe(
        "[A or B](a|b.md)",
      );
    });

    it("falls back to a markdown link for a note in a hidden folder", () => {
      useLinkFormat("wikilink");
      expect(pick([makeNoteMeta(".trash/old.md", "Old")], "Old")).toBe(
        "[Old](../.trash/old.md)",
      );
    });

    it("treats an unknown stored format as markdown", () => {
      useLinkFormat("obsidian");
      expect(pick([makeNoteMeta("notes/b.md", "B")], "B")).toBe("[B](b.md)");
    });
  });
});

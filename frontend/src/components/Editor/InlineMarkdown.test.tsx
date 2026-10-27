import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

// The note list wikilinks resolve against -- the real hook needs a
// NotesProvider, which would fetch (matches MarkdownPreview.test.tsx).
let notePaths: string[] = [];
vi.mock("../../context/NotesContext", async () => {
  const { NoteLookup } =
    await vi.importActual<typeof import("../../lib/wikilinks")>("../../lib/wikilinks");
  return { useNoteLookup: () => new NoteLookup(notePaths) };
});

import { InlineMarkdown } from "./InlineMarkdown";

function renderInline(text: string, currentPath = "notes/a.md") {
  return render(
    <MemoryRouter>
      <InlineMarkdown text={text} currentPath={currentPath} />
    </MemoryRouter>,
  );
}

describe("InlineMarkdown", () => {
  beforeEach(() => {
    notePaths = [];
  });

  it("links a wikilink to the note it resolves to, as the preview does", () => {
    notePaths = ["notes/note-id.md", "other/note-id.md"];
    renderInline("Ask [[note-id]] about it");

    expect(screen.getByRole("link", { name: "note-id" })).toHaveAttribute(
      "href",
      "/notes/notes/note-id.md",
    );
  });

  it("links a relative .md link in-app and an external one in a new tab", () => {
    const { container } = renderInline("[plan](b.md) and [site](https://example.com)");

    expect(screen.getByRole("link", { name: "plan" })).toHaveAttribute(
      "href",
      "/notes/notes/b.md",
    );
    expect(screen.getByRole("link", { name: "site" })).toHaveAttribute(
      "target",
      "_blank",
    );
    expect(container.querySelector("p")).toBeNull();
  });

  it("renders emphasis and inline code", () => {
    const { container } = renderInline("**Call** the _plumber_ about `pipe-3`");

    expect(container.querySelector("strong")).toHaveTextContent("Call");
    expect(container.querySelector("em")).toHaveTextContent("plumber");
    expect(container.querySelector("code")).toHaveTextContent("pipe-3");
  });

  it("drops a javascript: link target", () => {
    const { container } = renderInline("[x](javascript:alert(1))");

    for (const anchor of container.querySelectorAll("a")) {
      expect(anchor.getAttribute("href") ?? "").not.toMatch(/javascript:/i);
    }
  });

  it("shows raw HTML as text", () => {
    const { container } = renderInline('<img src=x onerror="alert(1)"> <b>bold</b>');

    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(container).toHaveTextContent('<img src=x onerror="alert(1)"> <b>bold</b>');
  });

  it.each([
    ["1. Call the plumber", "1. Call the plumber"],
    ["2) Second", "2) Second"],
    ["# Not a heading", "# Not a heading"],
    ["> Not a quote", "> Not a quote"],
    ["- Not a list", "- Not a list"],
    ["+ Not a list", "+ Not a list"],
    ["---", "---"],
    ["* * *", "* * *"],
    ["```js", "```js"],
    ["[ref]: https://example.com", "[ref]: https://example.com"],
  ])("renders %j inline, not as a block", (text, shown) => {
    const { container } = renderInline(text);

    for (const tag of ["ol", "ul", "li", "h1", "blockquote", "hr", "pre", "p"]) {
      expect(container.querySelector(tag)).toBeNull();
    }
    expect(container).toHaveTextContent(shown);
  });
});

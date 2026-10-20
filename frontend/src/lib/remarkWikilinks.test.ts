// @vitest-environment node
// Runs the transformer on hand-built syntax trees; the rendered result is
// covered by MarkdownPreview.test.tsx.
import { describe, expect, it } from "vitest";
import {
  type MdNode,
  remarkWikilinks,
  WIKILINK_EMBED,
  WIKILINK_TARGET,
} from "./remarkWikilinks";

function paragraph(...children: MdNode[]): MdNode {
  return { type: "root", children: [{ type: "paragraph", children }] };
}

function transform(tree: MdNode): MdNode[] {
  remarkWikilinks()(tree);
  return tree.children?.[0].children ?? [];
}

describe("remarkWikilinks", () => {
  it("splits text around links and image embeds", () => {
    const nodes = transform(
      paragraph({ type: "text", value: "a [[B|Bee]] b ![[c.png]] d ![[Note]]" }),
    );

    expect(nodes).toEqual([
      { type: "text", value: "a " },
      {
        type: "link",
        url: "",
        children: [{ type: "text", value: "Bee" }],
        data: { hProperties: { [WIKILINK_TARGET]: "B" } },
      },
      { type: "text", value: " b " },
      {
        type: "image",
        url: "",
        alt: "c.png",
        data: { hProperties: { [WIKILINK_EMBED]: "c.png" } },
      },
      { type: "text", value: " d " },
      {
        type: "link",
        url: "",
        children: [{ type: "text", value: "Note" }],
        data: { hProperties: { [WIKILINK_TARGET]: "Note" } },
      },
    ]);
  });

  it("leaves code, existing links and plain text untouched", () => {
    const children: MdNode[] = [
      { type: "inlineCode", value: "[[B]]" },
      { type: "link", url: "x.md", children: [{ type: "text", value: "[[B]]" }] },
      { type: "text", value: "no links here" },
    ];
    const tree = paragraph(...structuredClone(children));

    expect(transform(tree)).toEqual(children);
  });

  it("rewrites text nested in other inline nodes", () => {
    const [strong] = transform(
      paragraph({ type: "strong", children: [{ type: "text", value: "[[B]]" }] }),
    );

    expect(strong.children?.map((child) => child.type)).toEqual(["link"]);
  });
});

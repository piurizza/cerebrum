import { findWikilinks, isVaultImageTarget } from "./wikilinks";

/** The slice of the markdown syntax tree (mdast) this plugin touches. */
export interface MdNode {
  type: string;
  value?: string;
  url?: string;
  alt?: string;
  children?: MdNode[];
  data?: { hProperties?: Record<string, string> };
}

/** The `data-*` attributes a wikilink's `<a>`/`<img>` carries, as hast
 * property names (what `MarkdownPreview` reads from the element). */
export const WIKILINK_TARGET = "dataWikilinkTarget";
export const WIKILINK_EMBED = "dataWikilinkEmbed";

/**
 * Remark plugin: turns `[[wikilinks]]` in text into link nodes, and image
 * embeds (`![[photo.png]]`) into image nodes, each carrying the written
 * target for `MarkdownPreview` to resolve against the note list. Only
 * `text` nodes are rewritten, so code blocks and inline code -- separate
 * node types -- are left exactly as written. Links inside an existing
 * link's text are left alone too, since links can't nest.
 */
export function remarkWikilinks() {
  return (tree: MdNode) => {
    rewriteChildren(tree);
  };
}

function rewriteChildren(parent: MdNode): void {
  const children = parent.children;
  if (!children) return;
  for (let i = 0; i < children.length; i++) {
    const child = children[i];
    if (child.type === "text") {
      const replacement = splitText(child.value ?? "");
      if (replacement) {
        children.splice(i, 1, ...replacement);
        i += replacement.length - 1;
      }
    } else if (child.type !== "link" && child.type !== "linkReference") {
      rewriteChildren(child);
    }
  }
}

function splitText(value: string): MdNode[] | null {
  const links = findWikilinks(value);
  if (links.length === 0) return null;
  const nodes: MdNode[] = [];
  let last = 0;
  for (const link of links) {
    if (link.start > last) {
      nodes.push({ type: "text", value: value.slice(last, link.start) });
    }
    const label =
      link.alias ||
      (link.heading === null ? link.target : `${link.target}#${link.heading}`);
    if (link.embed && isVaultImageTarget(link.target)) {
      nodes.push({
        type: "image",
        url: "",
        alt: link.alias || link.target,
        data: { hProperties: { [WIKILINK_EMBED]: link.target } },
      });
    } else {
      nodes.push({
        type: "link",
        url: "",
        children: [{ type: "text", value: label }],
        data: {
          hProperties: { [WIKILINK_TARGET]: link.target },
        },
      });
    }
    last = link.end;
  }
  if (last < value.length) nodes.push({ type: "text", value: value.slice(last) });
  return nodes;
}

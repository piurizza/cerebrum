import type {
  Completion,
  CompletionContext,
  CompletionResult,
} from "@codemirror/autocomplete";
import { relativeLinkPath } from "../../lib/noteContent";
import { vaultLinkFormat } from "../../lib/vaultSettings";
import { isHiddenPath, NoteLookup } from "../../lib/wikilinks";
import type { NoteMeta } from "../../types/note";

const TRIGGER_PATTERN = /\[\[[^[\]]*/;
const MAX_RESULTS = 20;

/**
 * CodeMirror completion source: typing `[[` opens a note picker, refined
 * by whatever's typed after it. Inserts the link form the server is set
 * to (`vaultLinkFormat()`, read when the pick is made):
 *
 * - `markdown` (the default): `[title](relative/path.md)`, with the path
 *   relative to `currentPath`'s own directory, matching the backend's
 *   link-resolution rule.
 * - `wikilink`: `[[name]]`, by file name -- or the shortest part of its
 *   path that no other note shares -- with `|title` added when the title
 *   isn't the file name, so the preview shows the title.
 */
export function noteLinkCompletionSource(notes: NoteMeta[], currentPath: string) {
  return (context: CompletionContext): CompletionResult | null => {
    const match = context.matchBefore(TRIGGER_PATTERN);
    if (!match) return null;

    const query = match.text.slice(2).toLowerCase();
    const candidates = notes
      .filter((note) => note.path !== currentPath)
      .filter(
        (note) =>
          note.title.toLowerCase().includes(query) ||
          note.path.toLowerCase().includes(query),
      )
      .sort((a, b) => a.title.localeCompare(b.title))
      .slice(0, MAX_RESULTS);

    if (candidates.length === 0) return null;

    const options: Completion[] = candidates.map((note) => ({
      label: note.title,
      detail: note.path,
      apply(view, _completion, from, to) {
        const linkText =
          (vaultLinkFormat() === "wikilink" && wikilinkTo(note, notes)) ||
          `[${note.title}](${relativeLinkPath(currentPath, note.path)})`;
        const afterCursor = view.state.doc.sliceString(to, to + 2);
        const end = afterCursor === "]]" ? to + 2 : to;
        view.dispatch({
          changes: { from, to: end, insert: linkText },
          selection: { anchor: from + linkText.length },
        });
      },
    }));

    return { from: match.from, options, filter: false };
  };
}

// Characters a wikilink can't carry: brackets end it, `|` starts the
// alias, `#` the heading.
const WIKILINK_UNSAFE_TARGET = /[[\]|#]/;
const WIKILINK_UNSAFE_ALIAS = /[[\]|]/;

/** `[[name]]` or `[[name|title]]` for `note`, or null when no wikilink can
 * reach it -- its path holds a character a wikilink can't carry, or it's
 * in a hidden folder, which wikilinks never match (the caller falls back to
 * a markdown link). A title that can't be an alias is left out. */
function wikilinkTo(note: NoteMeta, notes: NoteMeta[]): string | null {
  if (isHiddenPath(note.path)) return null;
  const target = new NoteLookup(notes.map((n) => n.path)).shortestUnambiguousTarget(
    note.path,
  );
  if (WIKILINK_UNSAFE_TARGET.test(target)) return null;
  const fileName = note.path.slice(note.path.lastIndexOf("/") + 1).replace(/\.md$/, "");
  if (note.title === fileName || WIKILINK_UNSAFE_ALIAS.test(note.title)) {
    return `[[${target}]]`;
  }
  return `[[${target}|${note.title}]]`;
}

import type {
  Completion,
  CompletionContext,
  CompletionResult,
} from "@codemirror/autocomplete";
import { relativeLinkPath } from "../../lib/noteContent";
import type { NoteMeta } from "../../types/note";

const TRIGGER_PATTERN = /\[\[[^[\]]*/;
const MAX_RESULTS = 20;

/**
 * CodeMirror completion source: typing `[[` opens a note picker, refined
 * by whatever's typed after it. Always inserts a standard markdown link
 * `[title](relative/path.md)` -- never wikilink syntax (see SPEC.md
 * Product vision) -- with the path relative to `currentPath`'s own
 * directory, matching the backend's link-resolution rule.
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
        const linkPath = relativeLinkPath(currentPath, note.path);
        const linkText = `[${note.title}](${linkPath})`;
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

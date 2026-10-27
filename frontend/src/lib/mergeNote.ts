import { diff3Merge } from "node-diff3";

export type MergeResult = { ok: true; text: string } | { ok: false };

interface SplitText {
  lines: string[];
  trailingNewline: boolean;
}

// The final newline is merged on its own, not as an empty last line: an
// appended task line would otherwise collide with that empty line in every
// note that ends with a newline (almost all of them).
function split(text: string): SplitText {
  const trailingNewline = text.endsWith("\n");
  const body = trailingNewline ? text.slice(0, -1) : text;
  return {
    lines: body === "" && !trailingNewline ? [] : body.split("\n"),
    trailingNewline,
  };
}

function join(lines: string[], trailingNewline: boolean): string {
  const body = lines.join("\n");
  return trailingNewline && lines.length > 0 ? `${body}\n` : body;
}

// The lines `theirs` added after the whole of `base`, when that is all it
// changed: the shape a quick-add or an assistant's append produces. Null
// for any other change.
function appendedLines(base: string[], theirs: string[]): string[] | null {
  if (theirs.length <= base.length) return null;
  for (let i = 0; i < base.length; i++) {
    if (theirs[i] !== base[i]) return null;
  }
  return theirs.slice(base.length);
}

/** Three-way line merge of the editor's buffer (`mine`) with the file as
 * it is now on the server (`theirs`), both derived from `base`, the
 * content the editor last loaded or saved. Changes to different lines
 * combine. When `theirs` only appended lines at the end, the result is
 * `mine` followed by those lines, even where diff3 would call the end of
 * the note a conflict (an edited last line, or lines both sides added).
 * Any other overlap is refused, for the user to resolve. */
export function mergeNote(base: string, mine: string, theirs: string): MergeResult {
  const o = split(base);
  const a = split(mine);
  const b = split(theirs);
  // Merged like a line of its own: whichever side changed it wins.
  const trailingNewline =
    a.trailingNewline !== o.trailingNewline ? a.trailingNewline : b.trailingNewline;

  const regions = diff3Merge(a.lines, o.lines, b.lines, {
    excludeFalseConflicts: true,
  });
  if (regions.every((region) => region.ok !== undefined)) {
    return {
      ok: true,
      text: join(
        regions.flatMap((region) => region.ok ?? []),
        trailingNewline,
      ),
    };
  }

  const appended = appendedLines(o.lines, b.lines);
  if (appended) {
    return { ok: true, text: join([...a.lines, ...appended], trailingNewline) };
  }
  return { ok: false };
}

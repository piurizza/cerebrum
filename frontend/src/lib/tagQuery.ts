// The search query language of the sidebar search box, shared with
// `GET /api/search` and the MCP `search-notes` tool
// (backend/src/cerebrum/index/search_query.py): `#tag` keeps notes
// carrying that tag (or a tag nested under it, `#work` -> `work/clientA`),
// `-#tag` drops them, and `#"two words"` quotes a tag with a space. Both
// sides run the cases in fixtures/tag-query.json, so they can't drift apart.
//
// Words are never split here: JavaScript's `\w` is ASCII-only even with
// the `u` flag (`città` would become `citt`), so the text left once the
// tags are removed goes to the server unchanged and the server splits it.
import type { NoteMeta } from "../types/note";

/** A tag picked in the search box or on the front page. `tag` keeps the
 * spelling shown to the user; comparisons go through `normalizeTag`. */
export interface TagChip {
  tag: string;
  excluded: boolean;
}

export interface ParsedQueryText {
  text: string;
  include: string[];
  exclude: string[];
}

export interface TagCount {
  /** Normalised tag, unique per entry. */
  key: string;
  /** The spelling used by the most notes. */
  tag: string;
  /** Notes a chip for this tag would match, within the current selection. */
  count: number;
  /** `key` of the tag this one is nested under, if any. */
  parent: string | null;
}

export interface TagFragment {
  start: number;
  end: number;
  fragment: string;
  excluded: boolean;
}

// A tag starts the text or follows whitespace, so `pre#fix` stays a word.
// An unterminated quote runs to the end of the text.
const TAG_TOKEN = /(?<!\S)(-?)#(?:"([^"]*)"?|([^\s"]+))/gu;
// The tag being typed: a token reaching the caret, quoted or not.
const FRAGMENT_AT_END = /(?<!\S)(-?)#(?:"([^"]*)|([^\s"]*))$/u;
const WORD_CHARACTER = /[\p{L}\p{N}_]/u;
const SUGGESTION_LIMIT = 8;

function displayTag(tag: string): string {
  const trimmed = tag.trim();
  return trimmed.startsWith("#") ? trimmed.slice(1).trim() : trimmed;
}

/** One leading `#` dropped, trimmed, lower-cased -- the form two tags are
 * compared in, so `#Work` in a note's frontmatter matches `#work`. */
export function normalizeTag(tag: string): string {
  return displayTag(tag).toLowerCase();
}

/** Whether a note's tag satisfies a tag from the query: the same tag, or
 * one nested under it. */
export function tagMatches(noteTag: string, queryTag: string): boolean {
  const note = normalizeTag(noteTag);
  const query = normalizeTag(queryTag);
  return note === query || note.startsWith(`${query}/`);
}

export function parseQueryText(query: string): ParsedQueryText {
  const include: string[] = [];
  const exclude: string[] = [];
  const remaining = query.replace(
    TAG_TOKEN,
    (_match, minus: string, quoted: string | undefined, plain: string | undefined) => {
      const tag = normalizeTag(quoted ?? plain ?? "");
      if (tag) (minus ? exclude : include).push(tag);
      return " ";
    },
  );
  return { text: remaining.split(/\s+/).filter(Boolean).join(" "), include, exclude };
}

/** Whether the text holds anything the full-text search can match. */
export function hasWords(text: string): boolean {
  return WORD_CHARACTER.test(text);
}

export function noteMatchesTags(
  tags: readonly string[],
  chips: readonly TagChip[],
): boolean {
  return chips.every((chip) => {
    const found = tags.some((tag) => tagMatches(tag, chip.tag));
    return chip.excluded ? !found : found;
  });
}

// Every tag of a note plus the parents it is nested under, keyed by the
// normalised form, each with the spelling the note uses for it.
function expandTags(tags: readonly string[]): Map<string, string> {
  const expanded = new Map<string, string>();
  for (const tag of tags) {
    const segments = displayTag(tag).split("/");
    for (let i = 1; i <= segments.length; i++) {
      const spelling = segments.slice(0, i).join("/");
      const key = spelling.toLowerCase();
      if (key && !expanded.has(key)) expanded.set(key, spelling);
    }
  }
  return expanded;
}

/** Every tag in the vault, parents of nested tags included, sorted by
 * name. Counts are taken within the notes the chips match, so each one is
 * the number of results picking that tag would give. */
export function collectTagCounts(
  notes: readonly NoteMeta[],
  chips: readonly TagChip[],
): TagCount[] {
  const spellings = new Map<string, Map<string, number>>();
  const counts = new Map<string, number>();
  for (const note of notes) {
    const expanded = expandTags(note.tags);
    const inSelection = noteMatchesTags(note.tags, chips);
    for (const [key, spelling] of expanded) {
      const forKey = spellings.get(key) ?? new Map<string, number>();
      forKey.set(spelling, (forKey.get(spelling) ?? 0) + 1);
      spellings.set(key, forKey);
      counts.set(key, (counts.get(key) ?? 0) + (inSelection ? 1 : 0));
    }
  }
  return [...spellings.entries()]
    .map(([key, forKey]) => {
      const [tag] = [...forKey.entries()].sort(
        ([a, aCount], [b, bCount]) => bCount - aCount || a.localeCompare(b),
      )[0];
      const slash = key.lastIndexOf("/");
      return {
        key,
        tag,
        count: counts.get(key) ?? 0,
        parent: slash === -1 ? null : key.slice(0, slash),
      };
    })
    .sort((a, b) => a.key.localeCompare(b.key));
}

/** Tags for the suggestion list: those starting with the typed text
 * first, then those containing it, each by count. Tags already chosen and,
 * once something is chosen, tags that would give no results are left out. */
export function suggestTags(
  counts: readonly TagCount[],
  fragment: string,
  chips: readonly TagChip[],
): TagCount[] {
  const typed = normalizeTag(fragment);
  const chosen = new Set(chips.map((chip) => normalizeTag(chip.tag)));
  const byCount = (a: TagCount, b: TagCount) =>
    b.count - a.count || a.key.localeCompare(b.key);
  const candidates = counts.filter(
    (entry) => !chosen.has(entry.key) && (chips.length === 0 || entry.count > 0),
  );
  const prefix = candidates
    .filter((entry) => entry.key.startsWith(typed))
    .sort(byCount);
  const contains = candidates
    .filter((entry) => !entry.key.startsWith(typed) && entry.key.includes(typed))
    .sort(byCount);
  return [...prefix, ...contains].slice(0, SUGGESTION_LIMIT);
}

/** The query sent to the server: the chips as `#tag` / `-#tag`, then the
 * typed text unchanged. */
export function serializeQuery(text: string, chips: readonly TagChip[]): string {
  const tags = chips.map((chip) => {
    const tag = displayTag(chip.tag);
    return `${chip.excluded ? "-" : ""}#${/\s/.test(tag) ? `"${tag}"` : tag}`;
  });
  return [...tags, text.trim()].filter(Boolean).join(" ");
}

/** The `#tag` or `-#tag` being typed at the caret, if any. Only a token
 * the caret sits at the end of counts: a caret in the middle of `#work`
 * is editing a finished tag, not typing one. */
export function tagFragmentAt(text: string, caret: number): TagFragment | null {
  if (caret < text.length && !/\s/.test(text[caret])) return null;
  const match = FRAGMENT_AT_END.exec(text.slice(0, caret));
  if (!match) return null;
  return {
    start: match.index,
    end: caret,
    fragment: match[2] ?? match[3] ?? "",
    excluded: match[1] === "-",
  };
}

/**
 * Obsidian-style `[[wikilinks]]`: finding them in text and resolving a
 * written target to a note path. Mirrors the backend's
 * `backend/src/cerebrum/notes/wikilinks.py`; both test suites run the
 * shared cases in `fixtures/wikilink-resolution.json`, so the preview and
 * the graph agree on what every link points at.
 */

export interface Wikilink {
  embed: boolean;
  target: string;
  /** Null when absent. */
  heading: string | null;
  /** Null when absent; `""` for `[[Note|]]`. */
  alias: string | null;
  start: number;
  end: number;
}

// `!` (embed), then `[[`, then anything up to the first `]]` on the same
// line that doesn't itself contain a bracket.
const WIKILINK_PATTERN = /(!?)\[\[([^[\]\n]*)\]\]/g;
// `\|` is Obsidian's alias separator inside a table cell.
const ALIAS_SEPARATOR = /\\?\|/;

// A target ending in one of these is a file, not a note.
const ATTACHMENT_EXTENSIONS = new Set([
  ".png",
  ".jpg",
  ".jpeg",
  ".gif",
  ".webp",
  ".svg",
  ".bmp",
  ".avif",
  ".pdf",
  ".mp3",
  ".wav",
  ".m4a",
  ".ogg",
  ".flac",
  ".mp4",
  ".webm",
  ".mov",
  ".mkv",
  ".ogv",
]);

/** Images the server will find and serve from anywhere in the vault. */
const VAULT_IMAGE_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".gif", ".webp"]);

/** Every wikilink in `text`, in order. `[[]]` and `[[ ]]` are not links.
 * Code is not skipped here: the remark plugin only ever passes text that
 * isn't code. */
export function findWikilinks(text: string): Wikilink[] {
  const links: Wikilink[] = [];
  for (const match of text.matchAll(WIKILINK_PATTERN)) {
    let inner = match[2];
    let alias: string | null = null;
    const separator = ALIAS_SEPARATOR.exec(inner);
    if (separator) {
      alias = inner.slice(separator.index + separator[0].length);
      inner = inner.slice(0, separator.index);
    }
    const hashIndex = inner.indexOf("#");
    const target = (hashIndex === -1 ? inner : inner.slice(0, hashIndex)).trim();
    const heading = hashIndex === -1 ? null : inner.slice(hashIndex + 1);
    if (!target && !heading?.trim()) continue;
    const start = match.index;
    links.push({
      embed: match[1] === "!",
      target,
      heading,
      alias,
      start,
      end: start + match[0].length,
    });
  }
  return links;
}

function lastSegment(path: string): string {
  return path.slice(path.lastIndexOf("/") + 1);
}

/** Like Python's `PurePosixPath(path).suffix`. */
function suffix(path: string): string {
  const name = lastSegment(path);
  const dot = name.lastIndexOf(".");
  return dot > 0 && dot < name.length - 1 ? name.slice(dot) : "";
}

function folder(path: string): string {
  const slash = path.lastIndexOf("/");
  return slash === -1 ? "." : path.slice(0, slash);
}

function stripMd(target: string): string {
  return target.toLowerCase().endsWith(".md") ? target.slice(0, -3) : target;
}

export function isAttachmentTarget(target: string): boolean {
  return ATTACHMENT_EXTENSIONS.has(suffix(target).toLowerCase());
}

export function isVaultImageTarget(target: string): boolean {
  return VAULT_IMAGE_EXTENSIONS.has(suffix(target).toLowerCase());
}

/** The comparison form of a name: Unicode NFC (macOS writes accented
 * file names decomposed) and lowercase. */
export function nameKey(text: string): string {
  return text.normalize("NFC").toLowerCase();
}

export function isHiddenPath(path: string): boolean {
  return path.split("/").some((part) => part.startsWith("."));
}

/** The candidate a link written in `sourcePath` means when several files
 * match: the one in the same folder, then the shortest path (fewest
 * folders, then fewest characters), then alphabetical order. */
export function closestPath(candidates: string[], sourcePath: string): string {
  const sourceFolder = folder(sourcePath);
  const rank = (path: string) =>
    [
      folder(path) === sourceFolder ? 0 : 1,
      path.split("/").length,
      [...path].length,
    ] as const;
  return candidates.reduce((best, path) => {
    const [a, b] = [rank(path), rank(best)];
    for (let i = 0; i < a.length; i++) {
      if (a[i] !== b[i]) return a[i] < b[i] ? path : best;
    }
    return path < best ? path : best;
  });
}

/** The vault's note paths, indexed by name, for resolving wikilinks.
 * Build one per note list and resolve every link against it. */
export class NoteLookup {
  private readonly byName = new Map<string, string[]>();

  constructor(notePaths: Iterable<string>) {
    for (const path of notePaths) {
      if (isHiddenPath(path)) continue;
      const name = lastSegment(path);
      const stem = name.slice(0, name.length - suffix(name).length);
      const key = nameKey(stem);
      const paths = this.byName.get(key);
      if (paths) paths.push(path);
      else this.byName.set(key, [path]);
    }
  }

  /** The note `target` points at when written in `sourcePath`, or null.
   * See the backend's `NoteLookup.resolve` for the rules. */
  resolve(sourcePath: string, rawTarget: string): string | null {
    let target = stripMd(rawTarget.trim());
    const anchored = target.startsWith("/");
    target = target.replace(/^\/+|\/+$/g, "");
    if (!target) return anchored ? null : sourcePath;
    const parts = target.split("/");
    if (parts.some((part) => part === "." || part === ".." || part === "")) {
      return null;
    }
    const sameName = this.byName.get(nameKey(parts[parts.length - 1])) ?? [];
    let candidates = sameName;
    if (anchored || parts.length > 1) {
      const wanted = nameKey(target);
      candidates = sameName.filter((path) => nameKey(stripMd(path)) === wanted);
      if (!anchored && candidates.length === 0) {
        candidates = sameName.filter((path) =>
          nameKey(stripMd(path)).endsWith(`/${wanted}`),
        );
      }
    }
    return candidates.length > 0 ? closestPath(candidates, sourcePath) : null;
  }

  /** The shortest target that points at `path` from any note: the file
   * name when no other note shares it, otherwise the shortest trailing
   * part of the path only `path` ends with. A root-level note whose name
   * is shared gets the root-anchored `/Name`. */
  shortestUnambiguousTarget(path: string): string {
    const noExt = stripMd(path);
    const parts = noExt.split("/");
    const others = (this.byName.get(nameKey(parts[parts.length - 1])) ?? [])
      .filter((other) => other !== path)
      .map((other) => nameKey(stripMd(other)));
    for (let count = 1; count < parts.length; count++) {
      const tail = parts.slice(-count).join("/");
      const key = nameKey(tail);
      if (!others.some((other) => other === key || other.endsWith(`/${key}`))) {
        return tail;
      }
    }
    if (others.length === 0 || parts.length > 1) return noExt;
    return `/${noExt}`;
  }
}

const EXTERNAL_PREFIXES = ["http://", "https://", "mailto:", "#"];
const FRONTMATTER_PATTERN = /^---\r?\n[\s\S]*?\r?\n---\r?\n?/;

/**
 * Normalize a relative path (`.`/`..`/segments) against the linking note's
 * directory, producing a vault-relative path. Shared by `resolveLinkTarget`
 * and `resolveAttachmentTarget` -- both resolve a relative reference the
 * same way, they just differ on which targets they're willing to resolve at
 * all (`.md` files only vs. anything non-external).
 */
function normalizeRelativePath(sourcePath: string, target: string): string | null {
  const sourceDir = sourcePath.split("/").slice(0, -1);
  const combined = [...sourceDir, ...target.split("/")];

  const parts: string[] = [];
  for (const part of combined) {
    if (part === "." || part === "") continue;
    if (part === "..") {
      if (parts.length > 0) parts.pop();
      continue;
    }
    parts.push(part);
  }

  return parts.length > 0 ? parts.join("/") : null;
}

/**
 * Resolve a markdown link target relative to the linking note's directory.
 * Mirrors backend/src/cerebrum/notes/parser.py's resolve_link_target --
 * keep the two in sync (see SPEC.md section 3, "Link resolution rule").
 *
 * Returns the normalized vault-relative path if it points at a `.md` file,
 * or null if it's external/non-markdown (not something to intercept for
 * in-app navigation).
 */
export function resolveLinkTarget(sourcePath: string, target: string): string | null {
  if (EXTERNAL_PREFIXES.some((prefix) => target.startsWith(prefix))) {
    return null;
  }

  const withoutHash = target.split("#")[0];
  if (!withoutHash.endsWith(".md")) {
    return null;
  }

  return normalizeRelativePath(sourcePath, withoutHash);
}

/**
 * Resolve an embedded image's markdown `src` relative to the linking note's
 * directory, the same way `resolveLinkTarget` resolves `.md` links --
 * except attachments aren't `.md` files, so there's no extension
 * requirement. Still short-circuits `EXTERNAL_PREFIXES` so an absolute/
 * external image URL (e.g. `https://example.com/foo.png`) is correctly
 * identified as "don't try to fetch this through the attachments API" and
 * left for the caller to render as-is.
 */
export function resolveAttachmentTarget(
  sourcePath: string,
  target: string,
): string | null {
  if (EXTERNAL_PREFIXES.some((prefix) => target.startsWith(prefix))) {
    return null;
  }

  return normalizeRelativePath(sourcePath, target);
}

/** Strip the leading YAML frontmatter block, leaving just the note body. */
export function stripFrontmatter(rawContent: string): string {
  return rawContent.replace(FRONTMATTER_PATTERN, "");
}

const IDENTITY_FIELD_LINE = /^(?:title|created):.*\r?\n?/gm;

/** True when a matched `title:`/`created:` line's value is genuinely
 * confined to that one line -- safe to delete outright. A value that
 * opens a quote it doesn't close on the same line is PyYAML's actual
 * default rendering for a string containing an embedded newline (e.g.
 * `yaml.dump({"title": "Line one\nLine two"})` produces `title: 'Line
 * one\n\n  Line two'` across three physical lines, verified directly
 * against the backend's renderer) -- reachable via a raw API/MCP write
 * or hand-editing a template file outside the app, not just this app's
 * own (single-line) title editor. Deleting only the first line in that
 * case would leave the continuation lines orphaned in the frontmatter
 * block, which a real YAML parser can then silently fold into a
 * *different*, unrelated key (verified against the backend's parser --
 * the orphaned lines got absorbed into the neighboring `tags` list). */
function isSingleLineValue(line: string): boolean {
  const value = line.replace(/^[a-z]+:\s*/i, "").trimEnd();
  if (value.startsWith("'")) return /^'(?:[^']|'')*'$/.test(value);
  if (value.startsWith('"')) return /^"(?:[^"\\]|\\.)*"$/.test(value);
  return true;
}

/** Remove the `title` and `created` frontmatter keys from a note's raw
 * content, leaving everything else (body, other frontmatter such as
 * `tags`) unchanged. Used when applying a note template: the backend's
 * `write_note` only stamps a fresh `created` when the field is absent,
 * and `render_note` always emits an explicit `title`/`created` once
 * either has been set once -- which every template will have, since
 * templates are authored the same way as any note. Without this
 * stripping, a note created from a template would silently inherit the
 * *template's* creation date and literal title instead of getting its
 * own. A key whose value spills onto further lines is left untouched
 * instead (see `isSingleLineValue`) -- inheriting a stale title/date in
 * that rare case is a strict improvement over corrupting a neighboring
 * field, and it's the same outcome a fully-verbatim copy would have had
 * before this stripping existed at all. */
export function stripTemplateIdentityFields(rawContent: string): string {
  const match = rawContent.match(FRONTMATTER_PATTERN);
  if (!match) return rawContent;

  const frontmatter = match[0];
  const body = rawContent.slice(frontmatter.length);
  const strippedFrontmatter = frontmatter.replace(IDENTITY_FIELD_LINE, (line) =>
    isSingleLineValue(line) ? "" : line,
  );
  return strippedFrontmatter + body;
}

/**
 * Compute the relative link text to write in `sourcePath` so it resolves
 * to `targetPath` under the link-resolution rule (relative to the linking
 * file's own directory) -- the insertion-side inverse of
 * `resolveLinkTarget`. Mirrors backend/src/cerebrum/notes/parser.py's
 * `_relative_link_text` (via `posixpath.relpath`).
 */
export function relativeLinkPath(sourcePath: string, targetPath: string): string {
  const sourceDir = sourcePath.split("/").slice(0, -1);
  const targetParts = targetPath.split("/");
  const targetDir = targetParts.slice(0, -1);
  const targetFilename = targetParts.at(-1) as string;

  let commonLen = 0;
  while (
    commonLen < sourceDir.length &&
    commonLen < targetDir.length &&
    sourceDir[commonLen] === targetDir[commonLen]
  ) {
    commonLen++;
  }

  const upSegments = Array(sourceDir.length - commonLen).fill("..");
  const downSegments = [...targetDir.slice(commonLen), targetFilename];
  return [...upSegments, ...downSegments].join("/");
}

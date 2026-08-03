const EXTERNAL_PREFIXES = ["http://", "https://", "mailto:", "#"];
const FRONTMATTER_PATTERN = /^---\r?\n[\s\S]*?\r?\n---\r?\n?/;

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

  const sourceDir = sourcePath.split("/").slice(0, -1);
  const combined = [...sourceDir, ...withoutHash.split("/")];

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

/** Strip the leading YAML frontmatter block, leaving just the note body. */
export function stripFrontmatter(rawContent: string): string {
  return rawContent.replace(FRONTMATTER_PATTERN, "");
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

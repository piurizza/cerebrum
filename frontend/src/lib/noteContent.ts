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

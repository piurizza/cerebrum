// @vitest-environment node
// Pure functions, no DOM -- skip jsdom's window/document bootstrap cost.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  formatLinkTarget,
  frontmatterLineCount,
  relativeLinkPath,
  resolveAttachmentTarget,
  resolveLinkTarget,
  stripFrontmatter,
  stripTemplateIdentityFields,
} from "./noteContent";

describe("resolveLinkTarget", () => {
  it("returns null for an http:// link", () => {
    expect(resolveLinkTarget("notes/a.md", "http://example.com/b.md")).toBeNull();
  });

  it("returns null for an https:// link", () => {
    expect(resolveLinkTarget("notes/a.md", "https://example.com/b.md")).toBeNull();
  });

  it("returns null for a mailto: link", () => {
    expect(resolveLinkTarget("notes/a.md", "mailto:someone@example.com")).toBeNull();
  });

  it("returns null for a bare #fragment link", () => {
    expect(resolveLinkTarget("notes/a.md", "#heading")).toBeNull();
  });

  it("returns null for a target that does not end in .md", () => {
    expect(resolveLinkTarget("notes/a.md", "image.png")).toBeNull();
  });

  it("strips a #fragment before resolving", () => {
    expect(resolveLinkTarget("notes/a.md", "b.md#section-1")).toBe("notes/b.md");
  });

  it("normalizes . and .. segments relative to the source note's directory", () => {
    expect(resolveLinkTarget("notes/sub/a.md", "../b.md")).toBe("notes/b.md");
    expect(resolveLinkTarget("notes/sub/a.md", "./c.md")).toBe("notes/sub/c.md");
    expect(resolveLinkTarget("notes/sub/a.md", "../../d.md")).toBe("d.md");
  });
});

describe("resolveAttachmentTarget", () => {
  it("returns null for external prefixes", () => {
    expect(
      resolveAttachmentTarget("notes/a.md", "http://example.com/x.png"),
    ).toBeNull();
    expect(
      resolveAttachmentTarget("notes/a.md", "https://example.com/x.png"),
    ).toBeNull();
    expect(
      resolveAttachmentTarget("notes/a.md", "mailto:someone@example.com"),
    ).toBeNull();
    expect(resolveAttachmentTarget("notes/a.md", "#fragment")).toBeNull();
  });

  it("resolves a relative non-.md target, unlike resolveLinkTarget", () => {
    expect(resolveAttachmentTarget("notes/sub/a.md", "../images/photo.png")).toBe(
      "notes/images/photo.png",
    );
  });
});

describe("stripFrontmatter", () => {
  it("removes a well-formed leading frontmatter block", () => {
    const raw = "---\ntitle: Hello\ntags: [a, b]\n---\n# Body\n\nContent here.";
    expect(stripFrontmatter(raw)).toBe("# Body\n\nContent here.");
  });

  it("leaves content unchanged when no frontmatter block is present", () => {
    const raw = "# Body\n\nContent here.";
    expect(stripFrontmatter(raw)).toBe(raw);
  });
});

describe("frontmatterLineCount", () => {
  it("counts the lines stripFrontmatter removes, so body line N is file line N + count", () => {
    const raw = "---\ntitle: Hello\ntags: [a, b]\n---\n# Body\n- [ ] Task";
    expect(frontmatterLineCount(raw)).toBe(4);
    expect(raw.split("\n")[1 + 4]).toBe(stripFrontmatter(raw).split("\n")[1]);
  });

  it("counts CRLF frontmatter lines once each", () => {
    expect(frontmatterLineCount("---\r\ntitle: Hello\r\n---\r\nBody")).toBe(3);
  });

  it("is 0 without frontmatter, or with an opening boundary that never closes", () => {
    expect(frontmatterLineCount("# Body\n---\n")).toBe(0);
    expect(frontmatterLineCount("---\n- [ ] Not frontmatter after all\n")).toBe(0);
  });
});

describe("stripTemplateIdentityFields", () => {
  it("removes title and created lines, preserving other frontmatter and the body", () => {
    const raw =
      "---\ntitle: Meeting\ntags: [work]\ncreated: '2026-01-01T00:00:00+00:00'\n---\n# Agenda\n\nItems.";
    expect(stripTemplateIdentityFields(raw)).toBe(
      "---\ntags: [work]\n---\n# Agenda\n\nItems.",
    );
  });

  it("returns content unchanged when frontmatter has no title/created keys", () => {
    const raw = "---\ntags: [work]\n---\n# Agenda\n\nItems.";
    expect(stripTemplateIdentityFields(raw)).toBe(raw);
  });

  it("returns content unchanged when there is no frontmatter block", () => {
    const raw = "# Agenda\n\nItems.";
    expect(stripTemplateIdentityFields(raw)).toBe(raw);
  });

  it("leaves an empty-but-valid frontmatter block when title/created were the only keys", () => {
    const raw = "---\ntitle: Meeting\ncreated: '2026-01-01T00:00:00+00:00'\n---\nBody.";
    expect(stripTemplateIdentityFields(raw)).toBe("---\n---\nBody.");
  });

  it("strips a single-line quoted value normally", () => {
    const raw = "---\ntitle: 'Meeting'\ntags: [work]\n---\nBody.";
    expect(stripTemplateIdentityFields(raw)).toBe("---\ntags: [work]\n---\nBody.");
  });

  it("leaves a multi-line title untouched instead of corrupting the frontmatter that follows it", () => {
    // This is PyYAML's actual default rendering for a string containing an
    // embedded newline (verified against the real backend renderer):
    // `yaml.dump({"title": "Line one\nLine two"})` produces exactly this
    // three-physical-line single-quoted scalar. A naive line-level strip
    // would delete only the first line, leaving " Line two'" and the blank
    // line orphaned right before `tags:` -- which a real YAML parser
    // silently folds into the unrelated `tags` list (verified against the
    // real backend parser). Leaving it untouched is the safe fallback.
    const raw = "---\ntitle: 'Line one\n\n  Line two'\ntags:\n- work\n---\nBody.";
    expect(stripTemplateIdentityFields(raw)).toBe(raw);
  });
});

describe("relativeLinkPath", () => {
  it("produces a bare filename for two notes in the same directory", () => {
    expect(relativeLinkPath("notes/a.md", "notes/b.md")).toBe("b.md");
  });

  it("produces ../ segments for a nested-to-root link", () => {
    expect(relativeLinkPath("notes/sub/a.md", "root.md")).toBe("../../root.md");
  });

  it("produces down segments for a root-to-nested link", () => {
    expect(relativeLinkPath("root.md", "notes/sub/b.md")).toBe("notes/sub/b.md");
  });

  it("finds the common ancestor for two nested notes in different branches", () => {
    expect(relativeLinkPath("notes/a/x.md", "notes/b/y.md")).toBe("../b/y.md");
  });
});

interface LinkTargetCases {
  resolve: { name: string; source: string; target: string; expected: string | null }[];
  format: { name: string; path: string; expected: string }[];
}

const linkCases = JSON.parse(
  readFileSync(
    new URL("../../../fixtures/markdown-link-targets.json", import.meta.url),
    "utf-8",
  ),
) as LinkTargetCases;

describe("shared markdown link target cases", () => {
  it.each(linkCases.resolve.map((c) => [c.name, c] as const))("resolves %s", (_, c) => {
    expect(resolveLinkTarget(c.source, c.target)).toBe(c.expected);
  });

  it.each(linkCases.format.map((c) => [c.name, c] as const))("writes %s", (_, c) => {
    expect(formatLinkTarget(c.path)).toBe(c.expected);
  });
});

describe("resolveAttachmentTarget with special characters", () => {
  it("decodes an image path with spaces", () => {
    expect(
      resolveAttachmentTarget("notes/My Note.md", "My%20Note.attachments/a.png"),
    ).toBe("notes/My Note.attachments/a.png");
  });

  it("reads an image path in angle brackets", () => {
    expect(resolveAttachmentTarget("My Note.md", "<My Note.attachments/a b.png>")).toBe(
      "My Note.attachments/a b.png",
    );
  });
});

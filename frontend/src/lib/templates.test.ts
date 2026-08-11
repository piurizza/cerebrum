// @vitest-environment node
// Pure functions, no DOM -- skip jsdom's window/document bootstrap cost.
import { afterEach, describe, expect, it, vi } from "vitest";
import { makeNoteMeta } from "../test/factories";
import { hasRelevantTemplate, listTemplateOptions, templatesFolder } from "./templates";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("listTemplateOptions", () => {
  it("returns an empty list when no note path starts with the templates folder", () => {
    const notes = [makeNoteMeta("daily/2026-08-11.md"), makeNoteMeta("inbox/idea.md")];
    expect(listTemplateOptions(notes, "inbox")).toEqual([]);
  });

  it("returns a global template for any target folder, including the root", () => {
    const notes = [makeNoteMeta("templates/Meeting.md")];
    const expected = [
      { path: "templates/Meeting.md", name: "Meeting", scope: null, tier: "global" },
    ];
    expect(listTemplateOptions(notes, "")).toEqual(expected);
    expect(listTemplateOptions(notes, "work/anything")).toEqual(expected);
  });

  it("tiers a scoped template as matching-scope when the target folder shares the scope segment", () => {
    const notes = [makeNoteMeta("templates/standup/Standup.md")];
    expect(listTemplateOptions(notes, "standup")).toEqual([
      {
        path: "templates/standup/Standup.md",
        name: "Standup",
        scope: "standup",
        tier: "matching-scope",
      },
    ]);
  });

  it("keeps a non-matching scoped template visible as other-scope, not omitted", () => {
    const notes = [makeNoteMeta("templates/standup/Standup.md")];
    expect(listTemplateOptions(notes, "work")).toEqual([
      {
        path: "templates/standup/Standup.md",
        name: "Standup",
        scope: "standup",
        tier: "other-scope",
      },
    ]);
  });

  it("matches on any path segment, not just the first", () => {
    const notes = [makeNoteMeta("templates/standup/Standup.md")];
    expect(listTemplateOptions(notes, "work/standup")[0].tier).toBe("matching-scope");
  });

  it("scopes a deeply-nested template to only its first segment after the templates root", () => {
    const notes = [makeNoteMeta("templates/meetings/standup/Standup.md")];
    const [option] = listTemplateOptions(notes, "meetings");
    expect(option.scope).toBe("meetings");
    expect(option.tier).toBe("matching-scope");

    const [otherOption] = listTemplateOptions(notes, "standup");
    expect(otherOption.scope).toBe("meetings");
    expect(otherOption.tier).toBe("other-scope");
  });

  it("orders matching-scope first, then global, then other-scope, alphabetically within each tier", () => {
    const notes = [
      makeNoteMeta("templates/work/Zeta.md"),
      makeNoteMeta("templates/work/Alpha.md"),
      makeNoteMeta("templates/Beta.md"),
      makeNoteMeta("templates/Gamma.md"),
      makeNoteMeta("templates/personal/Delta.md"),
    ];
    const names = listTemplateOptions(notes, "work").map((o) => o.name);
    expect(names).toEqual(["Alpha", "Zeta", "Beta", "Gamma", "Delta"]);
  });

  it("falls back to the default folder and trims slashes from a custom VITE_TEMPLATES_FOLDER", () => {
    vi.stubEnv("VITE_TEMPLATES_FOLDER", "/journal-templates/");
    const notes = [makeNoteMeta("journal-templates/Meeting.md")];
    expect(listTemplateOptions(notes, "")).toEqual([
      {
        path: "journal-templates/Meeting.md",
        name: "Meeting",
        scope: null,
        tier: "global",
      },
    ]);
  });
});

describe("hasRelevantTemplate", () => {
  it("is false for an empty list", () => {
    expect(hasRelevantTemplate([])).toBe(false);
  });

  it("is false when every option is other-scope", () => {
    expect(
      hasRelevantTemplate([
        { path: "templates/a/A.md", name: "A", scope: "a", tier: "other-scope" },
      ]),
    ).toBe(false);
  });

  it("is true when at least one global or matching-scope option is present", () => {
    expect(
      hasRelevantTemplate([
        { path: "templates/a/A.md", name: "A", scope: "a", tier: "other-scope" },
        { path: "templates/B.md", name: "B", scope: null, tier: "global" },
      ]),
    ).toBe(true);
  });
});

describe("templatesFolder", () => {
  it("falls back to 'templates' when unset", () => {
    expect(templatesFolder()).toBe("templates");
  });
});

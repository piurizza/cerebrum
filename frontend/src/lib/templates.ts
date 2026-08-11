import type { NoteMeta } from "../types/note";
import { normalizeFolderEnvVar } from "./envFolder";
import { splitNotePath } from "./noteTree";

export type TemplateTier = "matching-scope" | "global" | "other-scope";

export interface TemplateOption {
  path: string;
  name: string;
  scope: string | null;
  tier: TemplateTier;
}

/** The vault-relative folder templates live in, configurable at build time
 * via `VITE_TEMPLATES_FOLDER`. Shares `dailyNote.ts`'s normalization via
 * `normalizeFolderEnvVar` (fallback + slash-trim). */
export function templatesFolder(): string {
  return normalizeFolderEnvVar(import.meta.env.VITE_TEMPLATES_FOLDER, "templates");
}

const TIER_RANK: Record<TemplateTier, number> = {
  "matching-scope": 0,
  global: 1,
  "other-scope": 2,
};

/** Discover and rank templates for a note about to be created in
 * `targetFolder`. A template directly under the templates root (no
 * subfolder) is `global`. One in a subfolder is scoped to that
 * subfolder's *first* path segment only -- deeper nesting below the scope
 * segment is just the template author's own organization and doesn't
 * change matching (e.g. `templates/meetings/standup/Standup.md`'s scope
 * is `"meetings"`, not `"standup"`). A scoped template's `scope` matches
 * `targetFolder` on any path segment, not just the first, compared
 * case-sensitively as an exact string -- see KTD2 in the note-templates
 * plan for why this breadth is deliberate. Non-matching scoped templates
 * are still returned (`tier: "other-scope"`), never hidden -- callers
 * decide whether to open a picker via `hasRelevantTemplate`, not by
 * filtering this list. */
export function listTemplateOptions(
  notes: NoteMeta[],
  targetFolder: string,
): TemplateOption[] {
  const folder = templatesFolder();
  const prefix = `${folder}/`;
  const targetSegments = targetFolder ? targetFolder.split("/") : [];

  const options: TemplateOption[] = [];
  for (const note of notes) {
    if (!note.path.startsWith(prefix)) continue;
    const remainder = note.path.slice(prefix.length);
    const { folder: remainderFolder, filename } = splitNotePath(remainder);
    const name = filename.replace(/\.md$/, "");

    if (!remainderFolder) {
      options.push({ path: note.path, name, scope: null, tier: "global" });
      continue;
    }

    const scope = remainderFolder.split("/")[0];
    const tier: TemplateTier = targetSegments.includes(scope)
      ? "matching-scope"
      : "other-scope";
    options.push({ path: note.path, name, scope, tier });
  }

  return options.sort((a, b) => {
    const rankDiff = TIER_RANK[a.tier] - TIER_RANK[b.tier];
    return rankDiff !== 0 ? rankDiff : a.name.localeCompare(b.name);
  });
}

/** Whether the picker is worth opening at all for this target folder: a
 * template with no bearing on this folder (`other-scope`) shouldn't add a
 * click to a note that will never use it (plan R3's skip rule). Does not
 * filter `options` -- once the picker *does* open, `other-scope` entries
 * are still shown, just deprioritized. */
export function hasRelevantTemplate(options: TemplateOption[]): boolean {
  return options.some((option) => option.tier !== "other-scope");
}

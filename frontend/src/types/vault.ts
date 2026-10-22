// Re-export of the generated OpenAPI schema type (see types/auth.ts for the
// pattern and why the `_Pin*` type exists). Do not hand-edit; edit the
// backend model and regenerate instead.
import type { components } from "../api/generated/schema";
import type { EqualKeys, Expect } from "./pinSchema";

export type VaultSettings = components["schemas"]["VaultSettings"];
export type _PinVaultSettings = Expect<
  EqualKeys<
    VaultSettings,
    "daily_note_folder" | "templates_folder" | "link_format" | "read_only"
  >
>;

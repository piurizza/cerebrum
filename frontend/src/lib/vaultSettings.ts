import { getVaultSettings } from "../api/client";
import type { VaultSettings } from "../types/vault";
import { normalizeVaultFolder } from "./vaultFolder";

/** The server's vault folder conventions (`GET /api/vault-settings`):
 * where "Today" creates daily notes, and which folder holds templates.
 *
 * Read synchronously through `vaultFolders()` -- `dailyNote.ts` and
 * `templates.ts` only need them inside click handlers, by which time
 * `loadVaultSettings()` (fired on app load and on login, next to
 * `syncVault()`) has normally finished. Until it has, and whenever the
 * server can't be reached, the last values the server sent are used
 * from `localStorage`, then the defaults. */
export interface VaultFolders {
  dailyNoteFolder: string;
  templatesFolder: string;
}

export const VAULT_SETTINGS_KEY = "cerebrum:vaultSettings";

const DEFAULT_DAILY_NOTE_FOLDER = "daily";
const DEFAULT_TEMPLATES_FOLDER = "templates";

let current: VaultFolders | null = null;

function toFolders(
  raw: Partial<Record<keyof VaultSettings, unknown>> | null,
): VaultFolders {
  const text = (value: unknown) => (typeof value === "string" ? value : undefined);
  return {
    dailyNoteFolder: normalizeVaultFolder(
      text(raw?.daily_note_folder),
      DEFAULT_DAILY_NOTE_FOLDER,
    ),
    templatesFolder: normalizeVaultFolder(
      text(raw?.templates_folder),
      DEFAULT_TEMPLATES_FOLDER,
    ),
  };
}

function readStored(): VaultFolders {
  try {
    const stored = window.localStorage.getItem(VAULT_SETTINGS_KEY);
    return toFolders(stored ? JSON.parse(stored) : null);
  } catch {
    // No storage (private window, node test environment) or a corrupt
    // value -- the defaults are a safe answer either way.
    return toFolders(null);
  }
}

export function vaultFolders(): VaultFolders {
  current ??= readStored();
  return current;
}

/** Fetch the server's settings and remember them. Never throws: offline,
 * logged out, or an older server without the endpoint all just keep the
 * values already in use. Fire-and-forget, like `syncVault()`. */
export async function loadVaultSettings(): Promise<void> {
  let settings: VaultSettings;
  try {
    settings = await getVaultSettings();
  } catch {
    return;
  }
  current = toFolders(settings);
  try {
    window.localStorage.setItem(VAULT_SETTINGS_KEY, JSON.stringify(settings));
  } catch {
    // Storage unavailable: the in-memory copy still serves this session.
  }
}

/** Forget the in-memory copy so the next read goes back to storage. For
 * tests only. */
export function resetVaultFoldersForTests(): void {
  current = null;
}

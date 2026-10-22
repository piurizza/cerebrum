import { getVaultSettings } from "../api/client";
import type { VaultSettings } from "../types/vault";
import { normalizeVaultFolder } from "./vaultFolder";

/** The server's vault conventions (`GET /api/vault-settings`): where
 * "Today" creates daily notes, which folder holds templates, which
 * link form the editor's `[[` picker inserts, and whether the vault is
 * read-only.
 *
 * Read synchronously through `vaultFolders()`, `vaultLinkFormat()` and
 * `vaultReadOnly()` --
 * `dailyNote.ts`, `templates.ts` and the link picker only need them
 * inside click handlers, by which time
 * `loadVaultSettings()` (fired on app load and on login, next to
 * `syncVault()`) has normally finished. Until it has, and whenever the
 * server can't be reached, the last values the server sent are used
 * from `localStorage`, then the defaults. `vaultReadOnly()` also drives
 * rendering (`useCanWrite`), so `subscribeVaultSettings()` lets React
 * re-render when a load lands. */
export interface VaultFolders {
  dailyNoteFolder: string;
  templatesFolder: string;
}

export type LinkFormat = VaultSettings["link_format"];

export const VAULT_SETTINGS_KEY = "cerebrum:vaultSettings";

const DEFAULT_DAILY_NOTE_FOLDER = "daily";
const DEFAULT_TEMPLATES_FOLDER = "templates";

interface CurrentSettings {
  folders: VaultFolders;
  linkFormat: LinkFormat;
  readOnly: boolean;
}

let current: CurrentSettings | null = null;
const listeners = new Set<() => void>();

function toSettings(
  raw: Partial<Record<keyof VaultSettings, unknown>> | null,
): CurrentSettings {
  const text = (value: unknown) => (typeof value === "string" ? value : undefined);
  return {
    folders: {
      dailyNoteFolder: normalizeVaultFolder(
        text(raw?.daily_note_folder),
        DEFAULT_DAILY_NOTE_FOLDER,
      ),
      templatesFolder: normalizeVaultFolder(
        text(raw?.templates_folder),
        DEFAULT_TEMPLATES_FOLDER,
      ),
    },
    // Anything unexpected (an older server without the field included)
    // means the long-standing default.
    linkFormat: raw?.link_format === "wikilink" ? "wikilink" : "markdown",
    // Unknown (never fetched, an older server, anything but `true`) counts
    // as writable: a failed first request must not lock writes for the
    // session, and the server refuses writes with a 403 regardless.
    readOnly: raw?.read_only === true,
  };
}

function readStored(): CurrentSettings {
  try {
    const stored = window.localStorage.getItem(VAULT_SETTINGS_KEY);
    return toSettings(stored ? JSON.parse(stored) : null);
  } catch {
    // No storage (private window, node test environment) or a corrupt
    // value -- the defaults are a safe answer either way.
    return toSettings(null);
  }
}

export function vaultFolders(): VaultFolders {
  current ??= readStored();
  return current.folders;
}

/** The link form the editor's `[[` picker inserts: `markdown` unless the
 * server is set to `wikilink`. */
export function vaultLinkFormat(): LinkFormat {
  current ??= readStored();
  return current.linkFormat;
}

/** Whether the server refuses writes to this vault
 * (`CEREBRUM_VAULT_READ_ONLY`). The cached value until this session's load
 * lands, `false` when nothing is known. Stable between loads, so it is a
 * valid `useSyncExternalStore` snapshot. */
export function vaultReadOnly(): boolean {
  current ??= readStored();
  return current.readOnly;
}

/** Called after each successful `loadVaultSettings()`. Returns the
 * unsubscribe function, the `useSyncExternalStore` contract. */
export function subscribeVaultSettings(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
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
  current = toSettings(settings);
  try {
    window.localStorage.setItem(VAULT_SETTINGS_KEY, JSON.stringify(settings));
  } catch {
    // Storage unavailable: the in-memory copy still serves this session.
  }
  for (const listener of listeners) listener();
}

/** Forget the in-memory copy so the next read goes back to storage. For
 * tests only. */
export function resetVaultFoldersForTests(): void {
  current = null;
}

import { useSyncExternalStore } from "react";
import { useOffline } from "../context/OfflineContext";
import { subscribeVaultSettings, vaultReadOnly } from "../lib/vaultSettings";

/** Whether the server refuses writes to this vault
 * (`CEREBRUM_VAULT_READ_ONLY`), re-rendering when vault settings load.
 * Cached value until then, `false` when nothing is known. Write controls
 * use it to decide *how* to be unavailable: hidden when the vault is
 * read-only (permanent), disabled when merely offline (temporary). */
export function useVaultReadOnly(): boolean {
  return useSyncExternalStore(subscribeVaultSettings, vaultReadOnly);
}

/** Whether a write (save, create, rename, delete, upload) can be attempted
 * right now: online and the vault is not read-only. The one place write
 * gating is decided -- kept out of `OfflineContext`, which mounts above
 * the router and must stay about connectivity alone. */
export function useCanWrite(): boolean {
  const { isOffline } = useOffline();
  const readOnly = useVaultReadOnly();
  return !isOffline && !readOnly;
}

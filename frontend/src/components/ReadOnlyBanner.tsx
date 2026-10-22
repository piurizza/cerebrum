import { useVaultReadOnly } from "../hooks/useCanWrite";

/** The single visible explanation for a read-only vault
 * (`CEREBRUM_VAULT_READ_ONLY`): its write controls are hidden rather than
 * disabled, and touch devices have no hover for a `title`, so this banner
 * is what says why. Not dismissible -- the condition lasts until the
 * server is reconfigured. `role="status"` (implicit `aria-live="polite"`)
 * announces it when vault settings land after the first paint, matching
 * `OfflineBanner`, under which it stacks when both apply. */
export function ReadOnlyBanner() {
  const readOnly = useVaultReadOnly();

  if (!readOnly) return null;

  return (
    <p className="read-only-banner" role="status">
      This vault is read-only
    </p>
  );
}

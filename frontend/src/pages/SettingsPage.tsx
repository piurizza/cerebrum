import {
  type FormEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useId,
  useState,
  useSyncExternalStore,
} from "react";
import {
  changePassword,
  createApiToken,
  createInvite,
  deactivateAccount,
  errorMessage,
  getAuthMethods,
  getLinkedIdentity,
  listAccounts,
  listApiTokens,
  revokeApiToken,
  startOidc,
  unlinkIdentity,
} from "../api/client";
import { ConfirmDialog } from "../components/ConfirmDialog/ConfirmDialog";
import { useAuth } from "../context/AuthContext";
import { useOffline } from "../context/OfflineContext";
import { useOneShotSearchParams } from "../hooks/useAuthMethods";
import { formatTimestamp } from "../lib/formatDate";
import { oidcErrorMessage } from "../lib/oidcErrors";
import {
  canInstall,
  isStandalone,
  promptInstall,
  subscribeInstall,
} from "../lib/pwaInstall";
import { redirectTo } from "../lib/redirect";
import type { AccountSummary, ApiTokenMeta, LinkedIdentity } from "../types/auth";

/** A plaintext secret (personal API token or invite token) shown exactly
 * once, right after it's minted -- the server never returns it again after
 * this response. Renders the value with a copy button and a persistent
 * warning, rather than a toast that could be missed. */
function OneTimeSecret({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    await navigator.clipboard.writeText(value);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="one-time-secret">
      <p className="error-text">
        {label} -- copy it now. You won't be able to see it again.
      </p>
      <div className="path-picker-trigger">
        <code className="note-path">{value}</code>
        <button type="button" className="btn btn-sm" onClick={handleCopy}>
          {copied ? "Copied!" : "Copy"}
        </button>
      </div>
    </div>
  );
}

// Mirrors the backend's floor (accounts/service.py's _MIN_PASSWORD_LENGTH)
// so the obvious mistake is caught before a round trip; the server still
// enforces it either way.
const MIN_PASSWORD_LENGTH = 12;

/** Change the signed-in account's password. The server signs out every
 * other session as part of the change, so this is also how to recover from
 * a leaked password. Exported for a focused test that doesn't need the
 * whole page's API mocks. */
export function ChangePasswordSection() {
  const { isOffline } = useOffline();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setDone(false);
    if (newPassword.length < MIN_PASSWORD_LENGTH) {
      setError(`New password must be at least ${MIN_PASSWORD_LENGTH} characters.`);
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("New passwords don't match.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await changePassword(currentPassword, newPassword);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
      setDone(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="settings-section">
      <h2>Change password</h2>
      <form onSubmit={handleSubmit} className="settings-stacked-form">
        <label className="rename-field">
          Current password
          <input
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={(event) => setCurrentPassword(event.target.value)}
          />
        </label>
        <label className="rename-field">
          New password
          <input
            type="password"
            autoComplete="new-password"
            value={newPassword}
            onChange={(event) => setNewPassword(event.target.value)}
          />
        </label>
        <label className="rename-field">
          Confirm new password
          <input
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={(event) => setConfirmPassword(event.target.value)}
          />
        </label>
        <button
          type="submit"
          className="btn btn-primary"
          disabled={
            saving || isOffline || !currentPassword || !newPassword || !confirmPassword
          }
        >
          {saving ? "Saving..." : "Change password"}
        </button>
      </form>
      {isOffline && (
        <p className="empty-hint">Reconnect to the server to change your password.</p>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {done && (
        <p role="status">Password changed. Every other device has been signed out.</p>
      )}
    </section>
  );
}

type IdentityState = LinkedIdentity | "loading" | "error";

/** Link this account to the configured sign-in provider, or unlink it
 * (R8, R9). Linking is a round trip through the provider: `startOidc`
 * returns the provider's URL and the callback brings the browser back to
 * `/settings`, with `?oidc_error=<code>` when it failed. */
function SignInProviderSection({
  providerName,
  identity,
  initialError,
  onChanged,
}: {
  providerName: string;
  identity: IdentityState;
  initialError: string | null;
  onChanged: () => void;
}) {
  const { isOffline } = useOffline();
  const headingId = useId();
  const unlinkHintId = useId();
  const [currentPassword, setCurrentPassword] = useState("");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(initialError);
  const [confirmingUnlink, setConfirmingUnlink] = useState(false);
  const [unlinking, setUnlinking] = useState(false);
  const [unlinkError, setUnlinkError] = useState<string | null>(null);

  async function handleLink(event: FormEvent) {
    event.preventDefault();
    if (typeof identity !== "object") return;
    setError(null);
    setStarting(true);
    try {
      // An account with a password must re-enter it (KTD5), so a stolen
      // short-lived access token can't add a lasting way in.
      const { authorization_url } = await startOidc(
        identity.has_password
          ? { intent: "link", current_password: currentPassword }
          : { intent: "link" },
      );
      redirectTo(authorization_url);
    } catch (err) {
      setError(errorMessage(err));
      setStarting(false);
    }
  }

  async function handleUnlink() {
    setUnlinking(true);
    setUnlinkError(null);
    try {
      await unlinkIdentity();
      setConfirmingUnlink(false);
      onChanged();
    } catch (err) {
      setUnlinkError(errorMessage(err));
    } finally {
      setUnlinking(false);
    }
  }

  let body: ReactNode;
  if (identity === "loading") {
    body = <p className="loading-indicator">Loading...</p>;
  } else if (identity === "error") {
    body = (
      <p className="error-text" role="alert">
        Could not load your sign-in provider link.
      </p>
    );
  } else if (identity.linked) {
    body = (
      <>
        <p>
          Linked to {providerName} as{" "}
          <strong>{identity.display_name ?? "an account with no name"}</strong>.
        </p>
        <div>
          <button
            type="button"
            className="btn btn-danger-outline"
            disabled={isOffline || !identity.password_usable}
            aria-describedby={identity.password_usable ? undefined : unlinkHintId}
            onClick={() => {
              setUnlinkError(null);
              setConfirmingUnlink(true);
            }}
          >
            Unlink
          </button>
        </div>
        {!identity.password_usable && (
          <p id={unlinkHintId} className="empty-hint">
            Your account has no password that signs you in, so unlinking {providerName}{" "}
            would lock you out.
          </p>
        )}
      </>
    );
  } else {
    body = (
      <>
        <p className="empty-hint">
          Link your {providerName} account to sign in to Cerebrum with it.
        </p>
        <form onSubmit={handleLink} className="settings-stacked-form">
          {identity.has_password && (
            <label className="rename-field">
              Current password
              <input
                type="password"
                autoComplete="current-password"
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
              />
            </label>
          )}
          <button
            type="submit"
            className="btn btn-primary"
            disabled={
              starting || isOffline || (identity.has_password && !currentPassword)
            }
          >
            Link {providerName} account
          </button>
        </form>
      </>
    );
  }

  return (
    <section className="settings-section" aria-labelledby={headingId}>
      <h2 id={headingId}>Sign-in provider</h2>
      {body}
      {isOffline && typeof identity === "object" && (
        <p className="empty-hint">
          Reconnect to the server to link or unlink {providerName}.
        </p>
      )}
      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}
      {confirmingUnlink && (
        <ConfirmDialog
          title="Unlink sign-in provider"
          message={`Unlink ${providerName}? You won't be able to sign in with it until you link it again; your password still works.`}
          confirmLabel="Unlink"
          error={unlinkError}
          busy={unlinking}
          onConfirm={handleUnlink}
          onCancel={() => setConfirmingUnlink(false)}
        />
      )}
    </section>
  );
}

function ApiTokensSection() {
  const [tokens, setTokens] = useState<ApiTokenMeta[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [newToken, setNewToken] = useState<string | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<ApiTokenMeta | null>(null);
  const [revoking, setRevoking] = useState(false);
  const [revokeError, setRevokeError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    listApiTokens()
      .then((result) => {
        setTokens(result);
        setError(null);
      })
      .catch((err: unknown) => setError(errorMessage(err)));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) return;
    setCreating(true);
    setError(null);
    try {
      const result = await createApiToken(trimmed);
      setNewToken(result.token);
      setName("");
      refresh();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setCreating(false);
    }
  }

  async function handleRevoke() {
    if (!revokeTarget) return;
    setRevoking(true);
    setRevokeError(null);
    try {
      await revokeApiToken(revokeTarget.id);
      setRevokeTarget(null);
      refresh();
    } catch (err) {
      setRevokeError(errorMessage(err));
    } finally {
      setRevoking(false);
    }
  }

  return (
    <section className="settings-section">
      <h2>Personal API tokens</h2>

      {newToken && <OneTimeSecret label="New API token" value={newToken} />}

      <form onSubmit={handleCreate} className="settings-inline-form">
        <label className="rename-field">
          Name
          <input
            type="text"
            placeholder="e.g. laptop"
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        <button
          type="submit"
          className="btn btn-primary"
          disabled={creating || !name.trim()}
        >
          {creating ? "Generating..." : "Generate new token"}
        </button>
      </form>

      {error && (
        <p className="error-text" role="alert">
          {error}
        </p>
      )}

      {tokens.length === 0 ? (
        <p className="empty-hint">No API tokens yet.</p>
      ) : (
        <ul className="settings-list">
          {tokens.map((token) => (
            <li key={token.id} className="settings-list-item">
              <div className="settings-list-item-main">
                <span className="settings-list-item-name">{token.name}</span>
                {token.revoked && <span className="tag-pill">Revoked</span>}
              </div>
              <div className="settings-list-item-meta">
                <span>Created {formatTimestamp(token.created_at)}</span>
                <span className="note-meta-sep">·</span>
                <span>
                  Last used{" "}
                  {token.last_used_at ? formatTimestamp(token.last_used_at) : "never"}
                </span>
              </div>
              {!token.revoked && (
                <button
                  type="button"
                  className="btn btn-sm btn-danger-outline"
                  onClick={() => {
                    setRevokeError(null);
                    setRevokeTarget(token);
                  }}
                >
                  Revoke
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {revokeTarget && (
        <ConfirmDialog
          title="Revoke API token"
          message={`Revoke "${revokeTarget.name}"? Any request using it will immediately stop working. This can't be undone.`}
          confirmLabel="Revoke"
          error={revokeError}
          busy={revoking}
          onConfirm={handleRevoke}
          onCancel={() => setRevokeTarget(null)}
        />
      )}
    </section>
  );
}

function AdminSection() {
  const { username: currentUsername } = useAuth();
  const [accounts, setAccounts] = useState<AccountSummary[] | null>(null);
  const [inviteToken, setInviteToken] = useState<string | null>(null);
  const [inviteError, setInviteError] = useState<string | null>(null);
  const [creatingInvite, setCreatingInvite] = useState(false);
  const [deactivateTarget, setDeactivateTarget] = useState<AccountSummary | null>(null);
  const [deactivating, setDeactivating] = useState(false);
  const [deactivateError, setDeactivateError] = useState<string | null>(null);

  const refresh = useCallback(() => {
    // A non-admin's request 403s here -- that's the signal this section
    // hides itself on, not a client-known `isAdmin` flag (see
    // `AuthContext`'s docstring for why). Any other failure is treated the
    // same way: absent, not an error banner, since a non-admin shouldn't
    // even learn this functionality exists.
    listAccounts()
      .then((result) => setAccounts(result))
      .catch(() => setAccounts(null));
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  async function handleCreateInvite() {
    setCreatingInvite(true);
    setInviteError(null);
    try {
      const result = await createInvite();
      setInviteToken(result.token);
    } catch (err) {
      setInviteError(errorMessage(err));
    } finally {
      setCreatingInvite(false);
    }
  }

  async function handleDeactivate() {
    if (!deactivateTarget) return;
    setDeactivating(true);
    setDeactivateError(null);
    try {
      await deactivateAccount(deactivateTarget.id);
      setDeactivateTarget(null);
      refresh();
    } catch (err) {
      setDeactivateError(errorMessage(err));
    } finally {
      setDeactivating(false);
    }
  }

  if (!accounts) {
    return null;
  }

  return (
    <section className="settings-section">
      <h2>Accounts (admin)</h2>

      {inviteToken && <OneTimeSecret label="New invite token" value={inviteToken} />}

      <button
        type="button"
        className="btn btn-primary"
        onClick={handleCreateInvite}
        disabled={creatingInvite}
      >
        {creatingInvite ? "Generating..." : "Generate invite"}
      </button>
      {inviteError && (
        <p className="error-text" role="alert">
          {inviteError}
        </p>
      )}

      <ul className="settings-list">
        {accounts.map((account) => {
          // `currentUsername` is only known when this session logged in on
          // this page load (see `AuthContext`'s docstring) -- after a
          // reload-restored session it's `null`, so self can't be
          // reliably excluded client-side. The backend itself still
          // rejects self-deactivation with a 403 either way (surfaced via
          // `deactivateError` above), so this is a UI nicety, not the
          // actual safety boundary.
          const isSelf =
            currentUsername !== null && account.username === currentUsername;
          return (
            <li key={account.id} className="settings-list-item">
              <div className="settings-list-item-main">
                <span className="settings-list-item-name">{account.username}</span>
                {account.is_admin && <span className="tag-pill">Admin</span>}
                <span className="tag-pill">
                  {account.is_active ? "Active" : "Inactive"}
                </span>
              </div>
              {account.is_active && !isSelf && (
                <button
                  type="button"
                  className="btn btn-sm btn-danger-outline"
                  onClick={() => {
                    setDeactivateError(null);
                    setDeactivateTarget(account);
                  }}
                >
                  Deactivate
                </button>
              )}
            </li>
          );
        })}
      </ul>

      {deactivateTarget && (
        <ConfirmDialog
          title="Deactivate account"
          message={`Deactivate "${deactivateTarget.username}"? This immediately revokes their session and API tokens. This can't be undone.`}
          confirmLabel="Deactivate"
          error={deactivateError}
          busy={deactivating}
          onConfirm={handleDeactivate}
          onCancel={() => setDeactivateTarget(null)}
        />
      )}
    </section>
  );
}

/** Android/Chrome in-app install control (R17). Shows only when a
 * `beforeinstallprompt` event has been captured and the app isn't already
 * installed -- iOS has no such event (that's the A2HS hint, U10). Exported
 * for a focused test that doesn't need the whole page's API mocks. */
export function InstallSection() {
  const installable = useSyncExternalStore(subscribeInstall, canInstall, () => false);

  if (!installable || isStandalone()) return null;

  return (
    <section className="settings-section">
      <h2>Install app</h2>
      <p className="empty-hint">
        Add Cerebrum to your home screen for a full-screen, app-like experience.
      </p>
      <button
        type="button"
        className="btn btn-primary"
        onClick={() => {
          void promptInstall();
        }}
      >
        Install
      </button>
    </section>
  );
}

const SETTINGS_QUERY_PARAMS = ["oidc_error"] as const;

export function SettingsPage() {
  const { oidc_error: oidcError } = useOneShotSearchParams(SETTINGS_QUERY_PARAMS);
  const [providerFromMethods, setProviderFromMethods] = useState<string | null>(null);
  const [methodsSettled, setMethodsSettled] = useState(false);
  const [identity, setIdentity] = useState<IdentityState>("loading");

  const loadIdentity = useCallback(() => {
    getLinkedIdentity()
      .then((result) => setIdentity(result))
      .catch(() => setIdentity("error"));
  }, []);

  useEffect(() => {
    // The methods call says whether a provider is configured before the
    // identity call settles, so the section can show its loading state;
    // the identity's own `provider_name` covers a failed methods call.
    getAuthMethods()
      .then((methods) => setProviderFromMethods(methods.oidc?.provider_name ?? null))
      .catch(() => setProviderFromMethods(null))
      .finally(() => setMethodsSettled(true));
    loadIdentity();
  }, [loadIdentity]);

  const providerName =
    providerFromMethods ??
    (typeof identity === "object" ? identity.provider_name : null);
  // Hidden only once the identity has loaded and says the password does
  // not sign this account in (KTD8); on a failed call, keep the section.
  const passwordUsable = typeof identity !== "object" || identity.password_usable;
  const linkError = oidcErrorMessage(oidcError);

  return (
    <div className="settings-page">
      <h1>Settings</h1>
      {linkError && !providerName && methodsSettled && identity !== "loading" && (
        <p className="error-text" role="alert">
          {linkError}
        </p>
      )}
      {passwordUsable && <ChangePasswordSection />}
      {providerName && (
        <SignInProviderSection
          providerName={providerName}
          identity={identity}
          initialError={linkError}
          onChanged={loadIdentity}
        />
      )}
      <ApiTokensSection />
      <AdminSection />
      <InstallSection />
    </div>
  );
}

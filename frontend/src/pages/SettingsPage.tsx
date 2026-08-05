import { type FormEvent, useCallback, useEffect, useState } from "react";
import {
  createApiToken,
  createInvite,
  deactivateAccount,
  errorMessage,
  listAccounts,
  listApiTokens,
  revokeApiToken,
} from "../api/client";
import { ConfirmDialog } from "../components/ConfirmDialog/ConfirmDialog";
import { useAuth } from "../context/AuthContext";
import { formatTimestamp } from "../lib/formatDate";
import type { AccountSummary, ApiTokenMeta } from "../types/auth";

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
        <button type="button" className="btn btn-copy" onClick={handleCopy}>
          {copied ? "Copied!" : "Copy"}
        </button>
      </div>
    </div>
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
                  className="btn btn-copy btn-danger-outline"
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
                  className="btn btn-copy btn-danger-outline"
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

export function SettingsPage() {
  return (
    <div className="settings-page">
      <h1>Settings</h1>
      <ApiTokensSection />
      <AdminSection />
    </div>
  );
}

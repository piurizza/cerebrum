"""What a verified OpenID Connect identity means for Cerebrum's accounts:
the account half of provider sign-in, next to `accounts/oidc.py`'s
protocol half.

An identity is `(issuer, subject)` from the ID token, stored in
`oidc_identities`. It only ever reaches an account through a link, and a
link is only ever made by redeeming an invite (here) or by a signed-in user
linking from Settings -- never by matching an email, a username or any
other claim (KTD2), so a provider account that happens to share an email
with a Cerebrum account can never take it over.

Failures raise `OidcError` with the code the callback redirects with; the
reason is logged here, where it is known.
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import UTC, datetime
from typing import cast

from cerebrum.accounts.oidc import OidcError, VerifiedIdentity
from cerebrum.accounts.service import NO_PASSWORD_HASH
from cerebrum.accounts.sessions import insert_session
from cerebrum.auth_db import auth_write_lock

logger = logging.getLogger(__name__)


def is_username_taken(auth_db: sqlite3.Connection, username: str) -> bool:
    """Whether an account already uses `username`. Only an early answer for
    the sign-up form: the `UNIQUE` constraint on `users.username` stays the
    sole arbiter when the account is actually created."""
    # Locked even though it's a single read -- see `auth_db.py`'s
    # `auth_write_lock` docstring.
    with auth_write_lock:
        row = auth_db.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone()
    return row is not None


def _linked_account(
    auth_db: sqlite3.Connection, identity: VerifiedIdentity
) -> sqlite3.Row | None:
    """The account `identity` is linked to, active or not. The caller holds
    `auth_write_lock`. Looked up under the identity's own issuer -- the
    configured one -- so links made under a previous provider are inert
    rather than wrong (KTD9)."""
    row: sqlite3.Row | None = auth_db.execute(
        """
        SELECT users.id, users.is_active
        FROM oidc_identities JOIN users ON users.id = oidc_identities.user_id
        WHERE oidc_identities.issuer = ? AND oidc_identities.subject = ?
        """,
        (identity.issuer, identity.subject),
    ).fetchone()
    return row


def _insert_identity(
    auth_db: sqlite3.Connection,
    user_id: int,
    identity: VerifiedIdentity,
    created_at: str,
) -> None:
    """Link `identity` to `user_id`. The caller holds `auth_write_lock` and
    the transaction, and has already checked the identity isn't linked."""
    auth_db.execute(
        """
        INSERT INTO oidc_identities (issuer, subject, user_id, display_name, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            identity.issuer,
            identity.subject,
            user_id,
            identity.display_name,
            created_at,
        ),
    )


def sign_in(auth_db: sqlite3.Connection, identity: VerifiedIdentity) -> str:
    """Start a session for the active account `identity` is linked to, and
    return its refresh token (the callback hands the browser no access
    token; the page's mount-time refresh gets one).

    Checks `is_active` but deliberately not the password lockout
    (`locked_until`): junk password attempts against a username must not
    lock its owner out of signing in through the provider (KTD10).

    Raises `OidcError("not_linked")` for an identity no account is linked
    to, and `OidcError("inactive")` for a deactivated account. Neither
    creates anything.
    """
    # One locked block for the lookup and the session insert, so the
    # account can't be deactivated between the two -- and so the admin
    # sync that hangs off provider sign-in later lands in the same
    # transaction as the session it applies to.
    with auth_write_lock, auth_db:
        account = _linked_account(auth_db, identity)
        if account is None:
            logger.info(
                "OIDC sign-in refused: %r at %r is not linked to any account",
                identity.subject,
                identity.issuer,
            )
            raise OidcError("not_linked")
        if not account["is_active"]:
            logger.info(
                "OIDC sign-in refused: account %s is deactivated", account["id"]
            )
            raise OidcError("inactive")
        _, refresh_token = insert_session(auth_db, account["id"])
    return refresh_token


def create_invited_account(
    auth_db: sqlite3.Connection,
    identity: VerifiedIdentity,
    username: str,
    invite_hash: str,
) -> str:
    """Redeem an invite through the provider (R6): create a non-admin
    account with no password, link `identity` to it, consume the invite and
    start a session, all in one transaction. Returns the refresh token.

    The invite was checked when the flow started; it is checked again here
    because it may have been used or have expired since. Mirrors
    `service.py`'s `_register_with_invite`: the user row goes in before the
    invite is consumed (`invites.consumed_by` references it), and any
    failure rolls the whole block back, so a lost race leaves no orphaned
    account or link and the invite unconsumed.

    Raises `OidcError` with `already_linked` (the identity already belongs
    to an account, active or not), `invite_invalid` or `username_taken`.
    """
    created_at = datetime.now(UTC).isoformat()
    # Raising inside this block is what rolls it back: `sqlite3.Connection`'s
    # context manager rolls back, rather than commits, when an exception
    # leaves it.
    with auth_write_lock, auth_db:
        if _linked_account(auth_db, identity) is not None:
            logger.info(
                "OIDC sign-up refused: %r at %r is already linked to an account",
                identity.subject,
                identity.issuer,
            )
            raise OidcError("already_linked")

        # The invite before the username, as `register_account()` orders
        # them: whether a username is taken is only told to someone holding
        # a usable invite.
        if not _invite_is_valid(auth_db, invite_hash, created_at):
            logger.info("OIDC sign-up refused: the invite is no longer valid")
            raise OidcError("invite_invalid")

        try:
            insert_cursor = auth_db.execute(
                """
                INSERT INTO users
                    (username, password_hash, is_admin, is_active, created_at)
                VALUES (?, ?, 0, 1, ?)
                """,
                (username, NO_PASSWORD_HASH, created_at),
            )
        except sqlite3.IntegrityError as exc:
            # Not pre-checked here -- the UNIQUE constraint on
            # `users.username` is the sole arbiter, as in `register_account()`.
            logger.info("OIDC sign-up refused: username %r is taken", username)
            raise OidcError("username_taken") from exc
        user_id = cast(int, insert_cursor.lastrowid)

        _insert_identity(auth_db, user_id, identity, created_at)

        consume_cursor = auth_db.execute(
            """
            UPDATE invites SET consumed_at = ?, consumed_by = ?
            WHERE token_hash = ? AND consumed_at IS NULL AND expires_at > ?
            """,
            (created_at, user_id, invite_hash, created_at),
        )
        if consume_cursor.rowcount != 1:
            # Unreachable while this block holds the lock after
            # `_invite_is_valid()`, but the conditional UPDATE is what
            # actually guarantees one redemption per invite.
            logger.info("OIDC sign-up refused: the invite was consumed meanwhile")
            raise OidcError("invite_invalid")

        _, refresh_token = insert_session(auth_db, user_id)
    return refresh_token


def _invite_is_valid(auth_db: sqlite3.Connection, invite_hash: str, now: str) -> bool:
    """`service.py`'s `find_valid_invite_token_hash()` by hash rather than by
    token -- the flow cookie carries only the hash. The caller holds
    `auth_write_lock`."""
    row = auth_db.execute(
        """
        SELECT 1 FROM invites
        WHERE token_hash = ? AND consumed_at IS NULL AND expires_at > ?
        """,
        (invite_hash, now),
    ).fetchone()
    return row is not None

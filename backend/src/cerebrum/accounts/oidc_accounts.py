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
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

from cerebrum.accounts.oidc import OidcError, VerifiedIdentity
from cerebrum.accounts.service import (
    NO_PASSWORD_HASH,
    User,
    has_password,
    invite_hash_is_valid,
    other_admin_has_password,
)
from cerebrum.accounts.sessions import insert_session
from cerebrum.auth_db import auth_write_lock
from cerebrum.settings import get_settings

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
        SELECT users.id, users.is_active, users.is_admin
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

    With `OIDC_ADMIN_GROUP` set, also sets the account's admin flag from
    the identity's groups (R10) -- see `_sync_admin()`.

    Raises `OidcError("not_linked")` for an identity no account is linked
    to, and `OidcError("inactive")` for a deactivated account. Neither
    creates anything.
    """
    # One locked block for the lookup, the admin sync and the session
    # insert, so the account can't be deactivated between them, and the
    # sync's last-admin check can't race another sign-in's demotion.
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
        _sync_admin(auth_db, account, identity)
        _, refresh_token = insert_session(auth_db, account["id"])
    return refresh_token


def _sync_admin(
    auth_db: sqlite3.Connection, account: sqlite3.Row, identity: VerifiedIdentity
) -> None:
    """Set the signing-in account's admin flag from its membership of
    `OIDC_ADMIN_GROUP`, in both directions (R10, KTD10). Off while the
    setting is empty. The caller holds `auth_write_lock` and the
    transaction.

    Promotion is unconditional. A demotion is skipped, with a warning, when
    no *other* active admin has a password they can sign in with: removing
    this admin could otherwise leave nobody able to sign in as an admin
    once the provider is down or misconfigured (Goal Capsule, stop
    condition c).
    """
    admin_group = get_settings().oidc_admin_group
    if not admin_group:
        return
    is_member = admin_group in identity.groups
    if is_member == bool(account["is_admin"]):
        return
    user_id = account["id"]
    if not is_member and not other_admin_has_password(auth_db, user_id):
        logger.warning(
            "OIDC admin sync: account %s is no longer in the %r group, but it "
            "stays an admin because no other active admin has a usable password",
            user_id,
            admin_group,
        )
        return
    auth_db.execute(
        "UPDATE users SET is_admin = ? WHERE id = ?", (int(is_member), user_id)
    )
    logger.info(
        "OIDC admin sync: account %s %s",
        user_id,
        "promoted to admin" if is_member else "demoted from admin",
    )


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
        if not invite_hash_is_valid(auth_db, invite_hash, created_at):
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
            # `invite_hash_is_valid()`, but the conditional UPDATE is what
            # actually guarantees one redemption per invite.
            logger.info("OIDC sign-up refused: the invite was consumed meanwhile")
            raise OidcError("invite_invalid")

        _, refresh_token = insert_session(auth_db, user_id)
    return refresh_token


# -- linking from Settings -----------------------------------------------------


class UnusablePasswordError(Exception):
    """Unlinking would leave the account with no password it can sign in
    with (KTD8): it has none, or the password switch has closed it."""


@dataclass(frozen=True)
class IdentityStatus:
    """What Settings shows about an account's sign-in methods."""

    linked: bool
    # The preferred username or email captured at link time (KTD9).
    display_name: str | None
    has_password: bool
    password_usable: bool


def link_identity(
    auth_db: sqlite3.Connection, identity: VerifiedIdentity, user_id: int
) -> None:
    """Link `identity` to the signed-in account `user_id` (R8), which
    started the flow from Settings. Each account links at most one identity
    per issuer, and each identity at most one account.

    Re-linking the account's own identity is a no-op. Raises `OidcError`
    with `inactive` (the account was deactivated since the flow started) or
    `already_linked` (the identity belongs to another account, or this
    account already has a different identity for this issuer). Neither
    changes anything.
    """
    created_at = datetime.now(UTC).isoformat()
    with auth_write_lock, auth_db:
        account = auth_db.execute(
            "SELECT is_active FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if account is None or not account["is_active"]:
            logger.info("OIDC link refused: account %s is deactivated", user_id)
            raise OidcError("inactive")

        linked = _linked_account(auth_db, identity)
        if linked is not None:
            if linked["id"] == user_id:
                return
            logger.info(
                "OIDC link refused: %r at %r is already linked to account %s",
                identity.subject,
                identity.issuer,
                linked["id"],
            )
            raise OidcError("already_linked")

        if _linked_subject(auth_db, user_id, identity.issuer) is not None:
            logger.info(
                "OIDC link refused: account %s already has an identity at %r",
                user_id,
                identity.issuer,
            )
            raise OidcError("already_linked")

        _insert_identity(auth_db, user_id, identity, created_at)


def identity_status(auth_db: sqlite3.Connection, user_id: int) -> IdentityStatus:
    """The account's link to the configured provider, and whether its
    password still signs in. With no provider configured nothing is
    linked."""
    issuer = _configured_issuer()
    with auth_write_lock:
        account = _password_row(auth_db, user_id)
        link = (
            None
            if issuer is None
            else auth_db.execute(
                """
                SELECT display_name FROM oidc_identities
                WHERE user_id = ? AND issuer = ?
                """,
                (user_id, issuer),
            ).fetchone()
        )
    linked = link is not None
    return IdentityStatus(
        linked=linked,
        display_name=link["display_name"] if link is not None else None,
        has_password=has_password(account["password_hash"]),
        password_usable=is_password_usable(
            account["password_hash"], bool(account["is_admin"]), linked=linked
        ),
    )


def unlink_identity(auth_db: sqlite3.Connection, user_id: int) -> None:
    """Remove the account's link to the configured provider (R9). A no-op
    when nothing is linked. Links made under a previous issuer stay, inert
    (KTD9).

    Raises `UnusablePasswordError`, changing nothing, when the account
    would be left with no password it can sign in with.
    """
    issuer = _configured_issuer()
    if issuer is None:
        return
    # One locked transaction for the check and the delete, so the account's
    # admin flag can't change between them.
    with auth_write_lock, auth_db:
        if _linked_subject(auth_db, user_id, issuer) is None:
            return
        account = _password_row(auth_db, user_id)
        if not is_password_usable(
            account["password_hash"], bool(account["is_admin"]), linked=True
        ):
            raise UnusablePasswordError(
                "You need a password you can sign in with before unlinking"
            )
        auth_db.execute(
            "DELETE FROM oidc_identities WHERE user_id = ? AND issuer = ?",
            (user_id, issuer),
        )


def is_password_usable(password_hash: str, is_admin: bool, *, linked: bool) -> bool:
    """Whether an account's password signs it in (KTD8): it has one, and
    password login is open to it (`_password_login_open()`)."""
    return has_password(password_hash) and _password_login_open(is_admin, linked=linked)


def _password_login_open(is_admin: bool, *, linked: bool) -> bool:
    """KTD11: the switch is on, or the account is an admin (break-glass),
    or it has no linked identity yet (so it can still sign in to link
    one)."""
    return get_settings().auth_password_login or is_admin or not linked


def password_login_open(auth_db: sqlite3.Connection, user: User) -> bool:
    """Whether `/api/auth/login` may sign `user` in with the password it
    just presented (KTD11). Only reads the link when the answer depends on
    it, so with the switch on login works as it always has."""
    if get_settings().auth_password_login or user.is_admin:
        return True
    issuer = _configured_issuer()
    if issuer is None:
        return True
    with auth_write_lock:
        linked = _linked_subject(auth_db, user.id, issuer) is not None
    return _password_login_open(user.is_admin, linked=linked)


def _configured_issuer() -> str | None:
    settings = get_settings()
    return settings.oidc_issuer if settings.oidc_enabled else None


def _linked_subject(
    auth_db: sqlite3.Connection, user_id: int, issuer: str
) -> str | None:
    """The subject the account has linked at `issuer`, if any. The caller
    holds `auth_write_lock`."""
    row = auth_db.execute(
        "SELECT subject FROM oidc_identities WHERE user_id = ? AND issuer = ?",
        (user_id, issuer),
    ).fetchone()
    return None if row is None else str(row["subject"])


def _password_row(auth_db: sqlite3.Connection, user_id: int) -> sqlite3.Row:
    """The caller holds `auth_write_lock`. The account exists: the caller
    is signed in as it, which `get_current_identity` just checked."""
    row: sqlite3.Row = auth_db.execute(
        "SELECT password_hash, is_admin FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    return row

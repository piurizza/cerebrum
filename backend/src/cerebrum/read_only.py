from __future__ import annotations

from cerebrum.settings import get_settings


class VaultReadOnlyError(Exception):
    """A vault write was attempted while CEREBRUM_VAULT_READ_ONLY is on."""


def ensure_vault_writable() -> None:
    """Called by every function that writes to the vault. Users never see
    this: the REST routes refuse with a 403 first (`api/deps.py`) and MCP
    write tools aren't registered. It's the net for a write path that
    forgets both."""
    if get_settings().cerebrum_vault_read_only:
        raise VaultReadOnlyError("This vault is read-only")

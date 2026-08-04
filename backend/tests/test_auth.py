from __future__ import annotations

import asyncio

import pytest

from cerebrum.auth import STUB_VALID_CREDENTIAL, AuthenticationError, verify_credential
from cerebrum.mcp.auth import SharedFunctionTokenVerifier


def test_verify_credential_rejects_missing_credential() -> None:
    with pytest.raises(AuthenticationError):
        asyncio.run(verify_credential(None))


def test_verify_credential_rejects_empty_credential() -> None:
    with pytest.raises(AuthenticationError):
        asyncio.run(verify_credential(""))


def test_verify_credential_accepts_the_stub_sentinel() -> None:
    subject = asyncio.run(verify_credential(STUB_VALID_CREDENTIAL))
    assert subject == "stub-subject"


def test_token_verifier_rejects_valid_sentinel_when_stub_auth_disallowed() -> None:
    verifier = SharedFunctionTokenVerifier(allow_stub_auth=False)
    result = asyncio.run(verifier.verify_token(STUB_VALID_CREDENTIAL))
    assert result is None


def test_token_verifier_accepts_valid_sentinel_when_stub_auth_allowed() -> None:
    verifier = SharedFunctionTokenVerifier(allow_stub_auth=True)
    result = asyncio.run(verifier.verify_token(STUB_VALID_CREDENTIAL))
    assert result is not None
    assert result.client_id == "stub-subject"


def test_token_verifier_rejects_wrong_credential_even_when_stub_auth_allowed() -> None:
    verifier = SharedFunctionTokenVerifier(allow_stub_auth=True)
    result = asyncio.run(verifier.verify_token("wrong"))
    assert result is None

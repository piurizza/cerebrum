from __future__ import annotations

import pytest

from cerebrum.settings import get_settings


def test_mcp_enabled_defaults_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_ENABLED", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().mcp_enabled is True
    finally:
        get_settings.cache_clear()


def test_mcp_enabled_reads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_ENABLED", "false")
    get_settings.cache_clear()
    try:
        assert get_settings().mcp_enabled is False
    finally:
        get_settings.cache_clear()


def test_mcp_allow_stub_auth_defaults_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MCP_ALLOW_STUB_AUTH", raising=False)
    get_settings.cache_clear()
    try:
        assert get_settings().mcp_allow_stub_auth is False
    finally:
        get_settings.cache_clear()

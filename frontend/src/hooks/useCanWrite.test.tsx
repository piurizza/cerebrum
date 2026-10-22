import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  loadVaultSettings,
  resetVaultFoldersForTests,
  VAULT_SETTINGS_KEY,
} from "../lib/vaultSettings";

const { mockGetVaultSettings } = vi.hoisted(() => ({ mockGetVaultSettings: vi.fn() }));
vi.mock("../api/client", () => ({ getVaultSettings: mockGetVaultSettings }));

const mockUseOffline =
  vi.fn<() => { isOffline: boolean; lastSyncedAt: string | null }>();
vi.mock("../context/OfflineContext", () => ({
  useOffline: () => mockUseOffline(),
}));

import { useCanWrite, useVaultReadOnly } from "./useCanWrite";

type VaultState = "writable" | "read-only" | "unknown";

function seedVault(state: VaultState) {
  if (state !== "unknown") {
    window.localStorage.setItem(
      VAULT_SETTINGS_KEY,
      JSON.stringify({ read_only: state === "read-only" }),
    );
  }
  resetVaultFoldersForTests();
}

beforeEach(() => {
  window.localStorage.clear();
  resetVaultFoldersForTests();
  mockGetVaultSettings.mockReset();
  mockUseOffline.mockReset();
});

afterEach(() => {
  window.localStorage.clear();
  resetVaultFoldersForTests();
});

describe("useCanWrite", () => {
  // Unknown (vault settings not resolved yet, nothing cached) counts as
  // writable -- the server 403s regardless, and a failed first request
  // must not lock writes for the whole session.
  it.each<[boolean, VaultState, boolean]>([
    [false, "writable", true],
    [false, "read-only", false],
    [false, "unknown", true],
    [true, "writable", false],
    [true, "read-only", false],
    [true, "unknown", false],
  ])("isOffline=%s, vault %s -> canWrite=%s", (isOffline, vault, expected) => {
    mockUseOffline.mockReturnValue({ isOffline, lastSyncedAt: null });
    seedVault(vault);

    const { result } = renderHook(() => useCanWrite());

    expect(result.current).toBe(expected);
  });

  it("re-renders when the vault settings load reports read-only", async () => {
    mockUseOffline.mockReturnValue({ isOffline: false, lastSyncedAt: null });
    mockGetVaultSettings.mockResolvedValue({ read_only: true });

    const { result } = renderHook(() => ({
      canWrite: useCanWrite(),
      vaultReadOnly: useVaultReadOnly(),
    }));
    expect(result.current).toEqual({ canWrite: true, vaultReadOnly: false });

    await act(async () => {
      await loadVaultSettings();
    });

    expect(result.current).toEqual({ canWrite: false, vaultReadOnly: true });
  });
});

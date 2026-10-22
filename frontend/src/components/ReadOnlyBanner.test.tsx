import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { loadVaultSettings } from "../lib/vaultSettings";
import { setCachedVaultReadOnly } from "../test/factories";

const { mockGetVaultSettings } = vi.hoisted(() => ({ mockGetVaultSettings: vi.fn() }));
vi.mock("../api/client", () => ({ getVaultSettings: mockGetVaultSettings }));

import { ReadOnlyBanner } from "./ReadOnlyBanner";

beforeEach(() => {
  mockGetVaultSettings.mockReset();
  setCachedVaultReadOnly(null);
});

describe("ReadOnlyBanner", () => {
  it("renders nothing on a writable vault", () => {
    setCachedVaultReadOnly(false);

    const { container } = render(<ReadOnlyBanner />);

    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing while the vault's settings are still unknown", () => {
    const { container } = render(<ReadOnlyBanner />);

    expect(container).toBeEmptyDOMElement();
  });

  it("explains a read-only vault in a status region, with no way to dismiss it", () => {
    setCachedVaultReadOnly(true);

    render(<ReadOnlyBanner />);

    expect(screen.getByRole("status")).toHaveTextContent("This vault is read-only");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("appears once the vault settings load reports read-only", async () => {
    mockGetVaultSettings.mockResolvedValue({ read_only: true });
    render(<ReadOnlyBanner />);
    expect(screen.queryByRole("status")).toBeNull();

    await act(async () => {
      await loadVaultSettings();
    });

    expect(screen.getByRole("status")).toHaveTextContent("This vault is read-only");
  });
});

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { formatTimestamp } from "../lib/formatDate";

const mockUseOffline =
  vi.fn<() => { isOffline: boolean; lastSyncedAt: string | null }>();
vi.mock("../context/OfflineContext", () => ({
  useOffline: () => mockUseOffline(),
}));

import { OfflineBanner } from "./OfflineBanner";

// Regression coverage for review finding #3 (2026-08-31 code review): this
// file did not exist before -- the entire R5 offline-signal component had
// no test, across all three of its render branches (hidden while online,
// stale-since copy, and the no-sync-yet fallback).
describe("OfflineBanner (R5)", () => {
  it("renders nothing while online", () => {
    mockUseOffline.mockReturnValue({ isOffline: false, lastSyncedAt: null });

    const { container } = render(<OfflineBanner />);

    expect(container).toBeEmptyDOMElement();
  });

  it("shows the formatted last-synced time when offline with a prior sync", () => {
    const lastSyncedAt = "2026-08-15T01:53:00.000Z";
    mockUseOffline.mockReturnValue({ isOffline: true, lastSyncedAt });

    render(<OfflineBanner />);

    const banner = screen.getByRole("status");
    expect(banner).toHaveTextContent(
      `Offline -- showing notes as of ${formatTimestamp(lastSyncedAt)}`,
    );
  });

  it("shows the no-sync-yet copy when offline before any sync has completed", () => {
    mockUseOffline.mockReturnValue({ isOffline: true, lastSyncedAt: null });

    render(<OfflineBanner />);

    expect(screen.getByRole("status")).toHaveTextContent(
      "Offline -- some notes may be unavailable",
    );
  });
});

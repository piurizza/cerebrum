// @vitest-environment node
// Pure logic against a mocked plugin, no DOM needed.
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockFetch = vi.fn();
vi.mock("@tauri-apps/plugin-http", () => ({
  fetch: (...args: unknown[]) => mockFetch(...args),
}));

import { checkHealth } from "./health";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("checkHealth", () => {
  it("resolves ok when the server responds 2xx", async () => {
    mockFetch.mockResolvedValue({ ok: true, status: 200 });

    const result = await checkHealth("http://localhost:8080");

    expect(result).toEqual({ ok: true });
  });

  it("checks the health endpoint relative to the configured URL", async () => {
    mockFetch.mockResolvedValue({ ok: true, status: 200 });

    await checkHealth("https://cerebrum.example.com/");

    expect(mockFetch).toHaveBeenCalledWith(
      "https://cerebrum.example.com/api/health",
      expect.objectContaining({ method: "GET" }),
    );
  });

  // Covers the plan's non-2xx edge case: reachable but unhealthy is still
  // a failure, not a success.
  it("resolves not-ok when the server responds non-2xx", async () => {
    mockFetch.mockResolvedValue({ ok: false, status: 503 });

    const result = await checkHealth("http://localhost:8080");

    expect(result.ok).toBe(false);
  });

  it("resolves not-ok when the request fails (network error or timeout)", async () => {
    mockFetch.mockRejectedValue(new Error("network error"));

    const result = await checkHealth("http://localhost:8080");

    expect(result.ok).toBe(false);
  });
});

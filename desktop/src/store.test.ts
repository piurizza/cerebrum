// @vitest-environment node
// Pure logic against a mocked plugin, no DOM needed.
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockStore = {
  get: vi.fn(),
  set: vi.fn(),
  save: vi.fn(),
};

vi.mock("@tauri-apps/plugin-store", () => ({
  load: vi.fn(() => Promise.resolve(mockStore)),
}));

import { getStoredServerUrl, setStoredServerUrl } from "./store";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("getStoredServerUrl", () => {
  it("returns the persisted URL when one exists", async () => {
    mockStore.get.mockResolvedValue("http://localhost:8080/");

    const result = await getStoredServerUrl();

    expect(result).toBe("http://localhost:8080/");
    expect(mockStore.get).toHaveBeenCalledWith("serverUrl");
  });

  it("returns null when nothing is stored yet", async () => {
    mockStore.get.mockResolvedValue(undefined);

    const result = await getStoredServerUrl();

    expect(result).toBeNull();
  });
});

describe("setStoredServerUrl", () => {
  it("persists the URL and flushes the store to disk", async () => {
    await setStoredServerUrl("http://localhost:8080/");

    expect(mockStore.set).toHaveBeenCalledWith("serverUrl", "http://localhost:8080/");
    expect(mockStore.save).toHaveBeenCalled();
  });
});

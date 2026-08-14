// @vitest-environment node
// Pure logic against a mocked plugin, no DOM needed.
import { beforeEach, describe, expect, it, vi } from "vitest";

const mockStore = {
  get: vi.fn(),
  set: vi.fn(),
  save: vi.fn(),
};

const mockLoad = vi.fn();
vi.mock("@tauri-apps/plugin-store", () => ({
  load: (...args: unknown[]) => mockLoad(...args),
}));

beforeEach(() => {
  vi.clearAllMocks();
  mockLoad.mockResolvedValue(mockStore);
  // Each test gets fresh module state -- store.ts's module-scoped
  // `storePromise` cache would otherwise leak the previous test's
  // (possibly rejected) open across tests.
  vi.resetModules();
});

describe("getStoredServerUrl", () => {
  it("returns the persisted URL when one exists", async () => {
    const { getStoredServerUrl } = await import("./store");
    mockStore.get.mockResolvedValue("http://localhost:8080/");

    const result = await getStoredServerUrl();

    expect(result).toBe("http://localhost:8080/");
    expect(mockStore.get).toHaveBeenCalledWith("serverUrl");
  });

  it("returns null when nothing is stored yet", async () => {
    const { getStoredServerUrl } = await import("./store");
    mockStore.get.mockResolvedValue(undefined);

    const result = await getStoredServerUrl();

    expect(result).toBeNull();
  });
});

describe("setStoredServerUrl", () => {
  it("persists the URL and flushes the store to disk", async () => {
    const { setStoredServerUrl } = await import("./store");

    await setStoredServerUrl("http://localhost:8080/");

    expect(mockStore.set).toHaveBeenCalledWith("serverUrl", "http://localhost:8080/");
    expect(mockStore.save).toHaveBeenCalled();
  });
});

describe("recovery after a failed store open", () => {
  it("retries load() on the next call instead of replaying the same rejection", async () => {
    const { getStoredServerUrl } = await import("./store");
    mockLoad.mockRejectedValueOnce(new Error("disk full"));

    await expect(getStoredServerUrl()).rejects.toThrow("disk full");

    // A naive cache of the rejected promise would make this call await
    // that same rejection forever; it should instead retry load() and
    // succeed once the underlying condition clears.
    mockStore.get.mockResolvedValue("http://localhost:8080/");
    const result = await getStoredServerUrl();

    expect(result).toBe("http://localhost:8080/");
    expect(mockLoad).toHaveBeenCalledTimes(2);
  });
});

import { beforeEach, describe, expect, it, vi } from "vitest";

const mockGetStoredServerUrl = vi.fn();
const mockSetStoredServerUrl = vi.fn();
vi.mock("./store", () => ({
  getStoredServerUrl: (...args: unknown[]) => mockGetStoredServerUrl(...args),
  setStoredServerUrl: (...args: unknown[]) => mockSetStoredServerUrl(...args),
}));

const mockCheckHealth = vi.fn();
vi.mock("./health", () => ({
  checkHealth: (...args: unknown[]) => mockCheckHealth(...args),
}));

import { initApp, navigation } from "./main";

function flush(): Promise<void> {
  // Two microtask hops: one for the `.then()` chain in the module under
  // test, one for the mocked async calls it awaits.
  return new Promise((resolve) => setTimeout(resolve, 0));
}

function fillAndSubmit(container: HTMLElement, value: string): void {
  const input = container.querySelector<HTMLInputElement>("#url-input");
  const form = container.querySelector<HTMLFormElement>("#url-form");
  if (!input || !form) {
    throw new Error("expected the URL form to be rendered");
  }
  input.value = value;
  form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
}

let container: HTMLElement;
let navigateSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  vi.clearAllMocks();
  document.body.innerHTML = "";
  container = document.createElement("div");
  document.body.appendChild(container);
  navigateSpy = vi.spyOn(navigation, "navigateTo").mockImplementation(() => {});
});

describe("first launch (F1)", () => {
  it("renders an empty form when no URL is stored", async () => {
    mockGetStoredServerUrl.mockResolvedValue(null);

    initApp(container);
    await flush();

    const input = container.querySelector<HTMLInputElement>("#url-input");
    expect(input).not.toBeNull();
    expect(input?.value).toBe("");
  });

  it("skips the form and health-checks directly when a URL is already stored", async () => {
    mockGetStoredServerUrl.mockResolvedValue("http://localhost:8080/");
    mockCheckHealth.mockResolvedValue({ ok: true });

    initApp(container);
    await flush();

    expect(container.querySelector("#url-form")).toBeNull();
    expect(mockCheckHealth).toHaveBeenCalledWith("http://localhost:8080/");
  });

  it("rejects empty input without persisting or health-checking", async () => {
    mockGetStoredServerUrl.mockResolvedValue(null);
    initApp(container);
    await flush();

    const form = container.querySelector<HTMLFormElement>("#url-form");
    form?.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await flush();

    expect(container.querySelector(".error")).not.toBeNull();
    expect(mockSetStoredServerUrl).not.toHaveBeenCalled();
    expect(mockCheckHealth).not.toHaveBeenCalled();
  });

  it("rejects a non-http/https scheme without persisting", async () => {
    mockGetStoredServerUrl.mockResolvedValue(null);
    initApp(container);
    await flush();

    fillAndSubmit(container, "javascript:alert(1)");
    await flush();

    expect(container.querySelector(".error")).not.toBeNull();
    expect(mockSetStoredServerUrl).not.toHaveBeenCalled();
  });

  it("persists a valid URL and hands off to the health-check", async () => {
    mockGetStoredServerUrl.mockResolvedValue(null);
    mockSetStoredServerUrl.mockResolvedValue(undefined);
    mockCheckHealth.mockResolvedValue({ ok: true });
    initApp(container);
    await flush();

    fillAndSubmit(container, "http://localhost:8080");
    await flush();

    expect(mockSetStoredServerUrl).toHaveBeenCalledWith("http://localhost:8080/");
    expect(mockCheckHealth).toHaveBeenCalledWith("http://localhost:8080/");
  });
});

describe("health-check in-flight state", () => {
  it("renders a connecting state while the health-check is pending", async () => {
    mockGetStoredServerUrl.mockResolvedValue("http://localhost:8080/");
    let resolveHealth: (value: { ok: true }) => void = () => {};
    mockCheckHealth.mockReturnValue(
      new Promise((resolve) => {
        resolveHealth = resolve;
      }),
    );

    initApp(container);
    await flush();

    expect(container.querySelector('[role="status"]')?.textContent).toContain(
      "Connecting",
    );
    // No stray interactive controls while pending -- nothing to click.
    expect(container.querySelector("button")).toBeNull();

    resolveHealth({ ok: true });
    await flush();
  });
});

describe("first-launch success (F1)", () => {
  it("navigates to the configured URL when the health-check succeeds", async () => {
    mockGetStoredServerUrl.mockResolvedValue("http://localhost:8080/");
    mockCheckHealth.mockResolvedValue({ ok: true });

    initApp(container);
    await flush();

    expect(navigateSpy).toHaveBeenCalledWith("http://localhost:8080/");
  });
});

describe("reconnect after failure (F2)", () => {
  async function reachErrorState(reason = "network error") {
    mockGetStoredServerUrl.mockResolvedValue("http://localhost:8080/");
    mockCheckHealth.mockResolvedValue({ ok: false, reason });
    initApp(container);
    await flush();
  }

  it("shows a retry/change-URL UI instead of a blank page on failure", async () => {
    await reachErrorState();

    expect(container.querySelector("#error-message")).not.toBeNull();
    expect(container.querySelector("#retry-button")).not.toBeNull();
    expect(container.querySelector("#change-url-button")).not.toBeNull();
  });

  it("moves focus to the error message on entering the error state", async () => {
    await reachErrorState();

    expect(document.activeElement).toBe(container.querySelector("#error-message"));
  });

  it("retries against the same URL without a relaunch (AE1)", async () => {
    await reachErrorState();
    mockCheckHealth.mockResolvedValue({ ok: true });

    container.querySelector<HTMLButtonElement>("#retry-button")?.click();
    await flush();

    expect(mockCheckHealth).toHaveBeenLastCalledWith("http://localhost:8080/");
    expect(navigateSpy).toHaveBeenCalledWith("http://localhost:8080/");
  });

  it("returns to a pre-filled form when changing the server URL (AE2)", async () => {
    await reachErrorState();

    container.querySelector<HTMLButtonElement>("#change-url-button")?.click();

    const input = container.querySelector<HTMLInputElement>("#url-input");
    expect(input?.value).toBe("http://localhost:8080/");
  });

  it("treats a non-2xx response as failure, not success", async () => {
    await reachErrorState("Server responded with 503");

    expect(navigateSpy).not.toHaveBeenCalled();
    expect(container.querySelector("#error-message")?.textContent).toContain("503");
  });
});

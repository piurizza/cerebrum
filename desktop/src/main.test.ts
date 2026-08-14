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

  // Security regression: a rejected submission re-renders the form with
  // the raw, unvalidated input as `prefill`. That value must never be
  // interpolated into an HTML attribute string (the input's `value="..."`
  // used to be built that way) -- a value like `" onmouseover="x` would
  // close the attribute early and inject a new one. Setting it via the
  // DOM property instead means it round-trips as plain data regardless of
  // content, and no second attribute ever appears on the element.
  it("does not let a rejected submission's raw input break out of the input's HTML attributes", async () => {
    mockGetStoredServerUrl.mockResolvedValue(null);
    initApp(container);
    await flush();

    fillAndSubmit(container, '" onmouseover="alert(1)');
    await flush();

    const input = container.querySelector<HTMLInputElement>("#url-input");
    expect(input?.value).toBe('" onmouseover="alert(1)');
    expect(input?.getAttribute("onmouseover")).toBeNull();
    // Only the four attributes the template itself declares -- nothing
    // injected by the submitted value.
    expect([...(input?.attributes ?? [])].map((a) => a.name).sort()).toEqual([
      "autocomplete",
      "id",
      "placeholder",
      "type",
    ]);
  });

  // Reliability: without a .catch() here, a rejected read leaves `#app`
  // exactly as it started -- an empty <main>, permanently, since nothing
  // else ever calls render().
  it("falls back to the form with an error when reading the stored URL fails", async () => {
    mockGetStoredServerUrl.mockRejectedValue(new Error("disk full"));
    initApp(container);
    await flush();

    const input = container.querySelector<HTMLInputElement>("#url-input");
    expect(input).not.toBeNull();
    expect(container.querySelector(".error")?.textContent).toContain("disk full");
  });

  it("falls back to the form with an error when saving the URL fails", async () => {
    mockGetStoredServerUrl.mockResolvedValue(null);
    mockSetStoredServerUrl.mockRejectedValue(new Error("permission denied"));
    initApp(container);
    await flush();

    fillAndSubmit(container, "http://localhost:8080");
    await flush();

    expect(container.querySelector(".error")?.textContent).toContain(
      "permission denied",
    );
    expect(mockCheckHealth).not.toHaveBeenCalled();
    // The URL survives the failure so the user isn't forced to retype it.
    const input = container.querySelector<HTMLInputElement>("#url-input");
    expect(input?.value).toBe("http://localhost:8080/");
  });

  // julik-frontend-races finding: without a synchronous state transition
  // on submit, the form (and its submit button) stays live during the
  // async store write, so a second submit before the first resolves would
  // start a second, concurrent health-check flow.
  it("ignores a second submit while the first is still in flight", async () => {
    mockGetStoredServerUrl.mockResolvedValue(null);
    let resolveSetStored: () => void = () => {};
    mockSetStoredServerUrl.mockReturnValue(
      new Promise<void>((resolve) => {
        resolveSetStored = resolve;
      }),
    );
    mockCheckHealth.mockResolvedValue({ ok: true });
    initApp(container);
    await flush();

    fillAndSubmit(container, "http://localhost:8080");
    await flush();
    // The form (and its submit button) is gone the instant the first
    // submit is accepted -- there is nothing left to submit a second time.
    expect(container.querySelector("#url-form")).toBeNull();

    resolveSetStored();
    await flush();

    expect(mockSetStoredServerUrl).toHaveBeenCalledTimes(1);
    expect(mockCheckHealth).toHaveBeenCalledTimes(1);
  });
});

describe("bootstrap entry point", () => {
  // main.ts registers its DOMContentLoaded listener once, at module-load
  // time (it's already imported statically at the top of this file) --
  // these tests fire that same listener directly via `window`, matching
  // exactly where it's registered (`window.addEventListener`), rather
  // than relying on whether DOMContentLoaded bubbles from document to
  // window the same way in jsdom as it does in a real webview.
  it("mounts into #app on DOMContentLoaded", async () => {
    document.body.innerHTML = '<main id="app"></main>';
    mockGetStoredServerUrl.mockResolvedValue(null);

    window.dispatchEvent(new Event("DOMContentLoaded"));
    await flush();

    const app = document.querySelector("#app");
    expect(app?.querySelector("#url-form")).not.toBeNull();
  });

  it("does not throw when #app is missing from the document", () => {
    document.body.innerHTML = "";

    expect(() => window.dispatchEvent(new Event("DOMContentLoaded"))).not.toThrow();
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

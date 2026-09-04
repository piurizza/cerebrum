import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  canInstall,
  isStandalone,
  promptInstall,
  subscribeInstall,
} from "./pwaInstall";

const realMatchMedia = window.matchMedia;

function matchMediaFor(...matching: string[]) {
  window.matchMedia = ((query: string) =>
    ({
      matches: matching.some((m) => query.includes(m)),
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(() => false),
    }) as unknown as MediaQueryList) as typeof window.matchMedia;
}

function fireBeforeInstallPrompt(outcome: "accepted" | "dismissed" = "accepted") {
  const event = new Event("beforeinstallprompt");
  Object.assign(event, {
    prompt: vi.fn().mockResolvedValue(undefined),
    userChoice: Promise.resolve({ outcome }),
  });
  window.dispatchEvent(event);
  return event as Event & { prompt: ReturnType<typeof vi.fn> };
}

beforeEach(() => {
  matchMediaFor(); // nothing matches by default
  // biome-ignore lint/suspicious/noExplicitAny: test-only navigator shim
  (navigator as any).standalone = undefined;
});

afterEach(() => {
  window.dispatchEvent(new Event("appinstalled")); // clears the deferred prompt
  window.matchMedia = realMatchMedia;
});

describe("isStandalone", () => {
  it("is true when display-mode standalone matches", () => {
    matchMediaFor("display-mode: standalone");
    expect(isStandalone()).toBe(true);
  });

  it("is true when navigator.standalone is true (iOS)", () => {
    // biome-ignore lint/suspicious/noExplicitAny: test-only navigator shim
    (navigator as any).standalone = true;
    expect(isStandalone()).toBe(true);
  });

  it("is false in a normal browser tab", () => {
    expect(isStandalone()).toBe(false);
  });
});

describe("install prompt capture", () => {
  it("canInstall() is false before any beforeinstallprompt", () => {
    expect(canInstall()).toBe(false);
  });

  it("captures the event and notifies subscribers", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeInstall(listener);
    fireBeforeInstallPrompt();
    expect(canInstall()).toBe(true);
    expect(listener).toHaveBeenCalled();
    unsubscribe();
  });

  it("promptInstall() returns 'unavailable' when nothing was captured", async () => {
    await expect(promptInstall()).resolves.toBe("unavailable");
  });

  it("on 'accepted' it prompts, resolves 'accepted', and clears canInstall()", async () => {
    const event = fireBeforeInstallPrompt("accepted");
    await expect(promptInstall()).resolves.toBe("accepted");
    expect(event.prompt).toHaveBeenCalledTimes(1);
    expect(canInstall()).toBe(false);
  });

  it("on 'dismissed' it keeps canInstall() true for a retry", async () => {
    fireBeforeInstallPrompt("dismissed");
    await expect(promptInstall()).resolves.toBe("dismissed");
    expect(canInstall()).toBe(true);
  });

  it("clears the deferred prompt on appinstalled", () => {
    fireBeforeInstallPrompt();
    expect(canInstall()).toBe(true);
    window.dispatchEvent(new Event("appinstalled"));
    expect(canInstall()).toBe(false);
  });
});

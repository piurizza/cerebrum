import { afterEach, describe, expect, it, vi } from "vitest";
import {
  clearSessionEstablished,
  consumeLoggedOut,
  LOGGED_OUT_KEY,
  markLoggedOut,
  markSessionEstablished,
  SESSION_ESTABLISHED_KEY,
  wasSessionEstablished,
} from "./sessionEstablished";

afterEach(() => {
  window.localStorage.clear();
  vi.restoreAllMocks();
});

describe("sessionEstablished", () => {
  it("defaults to not established and no tombstone", () => {
    expect(wasSessionEstablished()).toBe(false);
    expect(consumeLoggedOut()).toBe(false);
  });

  it("marks and persists the established flag", () => {
    markSessionEstablished();
    expect(wasSessionEstablished()).toBe(true);
    // Survives a "reload" -- the value is really in localStorage, not memory.
    expect(window.localStorage.getItem(SESSION_ESTABLISHED_KEY)).toBe("1");
  });

  it("clears the established flag", () => {
    markSessionEstablished();
    clearSessionEstablished();
    expect(wasSessionEstablished()).toBe(false);
  });

  it("marking a session established also drops a stale logout tombstone", () => {
    markLoggedOut();
    markSessionEstablished();
    expect(window.localStorage.getItem(LOGGED_OUT_KEY)).toBeNull();
    expect(consumeLoggedOut()).toBe(false);
  });

  it("the logout tombstone is one-shot", () => {
    markLoggedOut();
    expect(consumeLoggedOut()).toBe(true);
    expect(consumeLoggedOut()).toBe(false);
  });

  it("swallows a throwing localStorage.setItem", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("QuotaExceededError");
    });
    expect(() => markSessionEstablished()).not.toThrow();
    expect(() => markLoggedOut()).not.toThrow();
  });

  it("returns safe defaults when localStorage.getItem throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("SecurityError");
    });
    expect(wasSessionEstablished()).toBe(false);
    expect(consumeLoggedOut()).toBe(false);
  });
});

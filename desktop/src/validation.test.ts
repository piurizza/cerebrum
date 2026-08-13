// @vitest-environment node
// Pure function, no DOM -- skip jsdom's window/document bootstrap cost.
import { describe, expect, it } from "vitest";
import { validateServerUrl } from "./validation";

describe("validateServerUrl", () => {
  it("accepts a well-formed http URL", () => {
    const result = validateServerUrl("http://localhost:8080");
    expect(result).toEqual({ ok: true, url: "http://localhost:8080/" });
  });

  it("accepts a well-formed https URL", () => {
    const result = validateServerUrl("https://cerebrum.example.com");
    expect(result.ok).toBe(true);
  });

  it("trims surrounding whitespace before parsing", () => {
    const result = validateServerUrl("  http://localhost:8080  ");
    expect(result).toEqual({ ok: true, url: "http://localhost:8080/" });
  });

  it("rejects an empty string", () => {
    const result = validateServerUrl("");
    expect(result.ok).toBe(false);
  });

  it("rejects a whitespace-only string", () => {
    const result = validateServerUrl("   ");
    expect(result.ok).toBe(false);
  });

  it("rejects a string that doesn't parse as a URL", () => {
    const result = validateServerUrl("not a url");
    expect(result.ok).toBe(false);
  });

  // Security edge case (KTD9 / U2 test scenarios): the scheme allowlist is
  // what stops a javascript:/data:/file: value from reaching the health-check
  // fetch or window.location.href navigation in health.ts.
  it("rejects a javascript: scheme", () => {
    const result = validateServerUrl("javascript:alert(1)");
    expect(result.ok).toBe(false);
  });

  it("rejects a file: scheme", () => {
    const result = validateServerUrl("file:///etc/passwd");
    expect(result.ok).toBe(false);
  });

  it("rejects a data: scheme", () => {
    const result = validateServerUrl("data:text/html,<h1>hi</h1>");
    expect(result.ok).toBe(false);
  });
});

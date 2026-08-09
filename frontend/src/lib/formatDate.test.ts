import { describe, expect, it } from "vitest";
import { formatTimestamp } from "./formatDate";

describe("formatTimestamp", () => {
  it("returns a locale-formatted string for a valid ISO-8601 timestamp", () => {
    const result = formatTimestamp("2026-01-15T10:30:00Z");
    expect(result).not.toBeNull();
    expect(typeof result).toBe("string");
  });

  it("returns null for a null input", () => {
    expect(formatTimestamp(null)).toBeNull();
  });

  it("returns null for a string that does not parse as a date", () => {
    expect(formatTimestamp("not-a-date")).toBeNull();
  });
});

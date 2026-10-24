// @vitest-environment node
// Pure function, no DOM -- skip jsdom's window/document bootstrap cost.
import { describe, expect, it } from "vitest";
import { formatRelativeDate, formatTimestamp } from "./formatDate";

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

describe("formatRelativeDate", () => {
  // Compared against the same Intl formatters, so the test holds in any locale.
  const relative = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
  const NOW = new Date(2026, 9, 24, 15, 0);
  const daysAgo = (days: number) => new Date(2026, 9, 24 - days, 9, 0).toISOString();

  it("returns null for nothing or garbage", () => {
    expect(formatRelativeDate(null, NOW)).toBeNull();
    expect(formatRelativeDate("not-a-date", NOW)).toBeNull();
  });

  it("counts calendar days, not 24-hour spans", () => {
    expect(formatRelativeDate(daysAgo(0), NOW)).toBe(relative.format(0, "day"));
    expect(formatRelativeDate(daysAgo(1), NOW)).toBe(relative.format(-1, "day"));
    expect(formatRelativeDate(daysAgo(6), NOW)).toBe(relative.format(-6, "day"));
  });

  it("switches to weeks from 7 days to 27", () => {
    expect(formatRelativeDate(daysAgo(7), NOW)).toBe(relative.format(-1, "week"));
    expect(formatRelativeDate(daysAgo(27), NOW)).toBe(relative.format(-4, "week"));
  });

  it("shows the date itself from 28 days", () => {
    const value = daysAgo(28);
    expect(formatRelativeDate(value, NOW)).toBe(
      new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(
        new Date(value),
      ),
    );
  });
});

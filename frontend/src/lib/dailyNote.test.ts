// @vitest-environment node
// Pure functions, no DOM -- skip jsdom's window/document bootstrap cost.
import { afterEach, describe, expect, it, vi } from "vitest";
import { getDailyNoteDefaultBody, getTodayNotePath } from "./dailyNote";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("getTodayNotePath", () => {
  it("formats a fixed local date into the default daily folder", () => {
    // Month is 0-indexed in the Date constructor.
    expect(getTodayNotePath(new Date(2026, 7, 11))).toBe("daily/2026-08-11.md");
  });

  it("zero-pads single-digit months and days", () => {
    expect(getTodayNotePath(new Date(2026, 0, 5))).toBe("daily/2026-01-05.md");
  });

  it("falls back to the default folder when VITE_DAILY_NOTE_FOLDER is unset", () => {
    vi.stubEnv("VITE_DAILY_NOTE_FOLDER", undefined);
    expect(getTodayNotePath(new Date(2026, 7, 11))).toBe("daily/2026-08-11.md");
  });

  it("falls back to the default folder when VITE_DAILY_NOTE_FOLDER is an empty string", () => {
    // The `||`-not-`??` fix (KTD1): an explicitly-empty env value (a
    // plausible .env typo) must not produce a leading-slash path.
    vi.stubEnv("VITE_DAILY_NOTE_FOLDER", "");
    expect(getTodayNotePath(new Date(2026, 7, 11))).toBe("daily/2026-08-11.md");
  });

  it("uses a custom VITE_DAILY_NOTE_FOLDER value, trimming a trailing slash", () => {
    vi.stubEnv("VITE_DAILY_NOTE_FOLDER", "journal/");
    expect(getTodayNotePath(new Date(2026, 7, 11))).toBe("journal/2026-08-11.md");
  });

  it("computes the local calendar date, not the UTC one, at a local/UTC day boundary", () => {
    // KTD2 regression guard: pinning TZ is load-bearing, not optional --
    // CI runs ubuntu-latest with no TZ set, which defaults to UTC, where
    // local and UTC dates are identical for every instant. Without
    // pinning a non-UTC zone here, this test can't express the
    // divergence it exists to catch, and a regression back to
    // `toISOString()` (which converts to UTC first) would ship
    // undetected.
    vi.stubEnv("TZ", "America/New_York");
    // 2026-01-01T02:00:00Z is 2025-12-31 21:00 in America/New_York
    // (UTC-5) -- the local and UTC dates genuinely differ here.
    const date = new Date("2026-01-01T02:00:00Z");
    expect(getTodayNotePath(date)).toBe("daily/2025-12-31.md");
  });
});

describe("getDailyNoteDefaultBody", () => {
  it("returns an H1 heading with the formatted date and a trailing blank line", () => {
    const body = getDailyNoteDefaultBody(new Date(2026, 7, 11));
    expect(body.startsWith("# ")).toBe(true);
    expect(body.endsWith("\n\n")).toBe(true);
  });
});

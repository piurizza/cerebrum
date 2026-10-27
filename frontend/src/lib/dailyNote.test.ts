// @vitest-environment node
// Pure functions, no DOM -- skip jsdom's window/document bootstrap cost.
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getDailyNoteDefaultBody,
  getDailyNoteHeading,
  getTodayNotePath,
  localDateFromIso,
  localIsoDate,
} from "./dailyNote";

// The folder comes from the server via `vaultSettings.ts` (its own tests
// cover loading, storage and normalization); here it's just a value.
const folders = vi.hoisted(() => ({
  dailyNoteFolder: "daily",
  templatesFolder: "templates",
}));
vi.mock("./vaultSettings", () => ({ vaultFolders: () => folders }));

afterEach(() => {
  vi.unstubAllEnvs();
  folders.dailyNoteFolder = "daily";
});

describe("getTodayNotePath", () => {
  it("formats a fixed local date into the default daily folder", () => {
    // Month is 0-indexed in the Date constructor.
    expect(getTodayNotePath(new Date(2026, 7, 11))).toBe("daily/2026-08-11.md");
  });

  it("zero-pads single-digit months and days", () => {
    expect(getTodayNotePath(new Date(2026, 0, 5))).toBe("daily/2026-01-05.md");
  });

  it("uses the folder the server is configured with", () => {
    folders.dailyNoteFolder = "journal/daily";
    expect(getTodayNotePath(new Date(2026, 7, 11))).toBe("journal/daily/2026-08-11.md");
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

describe("localIsoDate", () => {
  it("is the local calendar day as YYYY-MM-DD, the day a tick records", () => {
    vi.stubEnv("TZ", "America/New_York");
    expect(localIsoDate(new Date("2026-01-01T02:00:00Z"))).toBe("2025-12-31");
    expect(localIsoDate(new Date(2026, 0, 5))).toBe("2026-01-05");
  });
});

describe("localDateFromIso", () => {
  it("is the start of that local calendar day, the inverse of localIsoDate", () => {
    vi.stubEnv("TZ", "America/New_York");
    const date = localDateFromIso("2026-01-05");
    expect(date).toEqual(new Date(2026, 0, 5));
    expect(localIsoDate(date)).toBe("2026-01-05");
    expect(localDateFromIso(localIsoDate(new Date(2026, 9, 26, 23, 30)))).toEqual(
      new Date(2026, 9, 26),
    );
  });
});

describe("getDailyNoteDefaultBody", () => {
  it("returns an H1 heading with the formatted date and a trailing blank line", () => {
    const body = getDailyNoteDefaultBody(new Date(2026, 7, 11));
    expect(body.startsWith("# ")).toBe(true);
    expect(body.endsWith("\n\n")).toBe(true);
  });
});

describe("getDailyNoteHeading", () => {
  it("is the default body's heading text, without the `# `", () => {
    const date = new Date(2026, 9, 26);
    expect(getDailyNoteDefaultBody(date)).toBe(`# ${getDailyNoteHeading(date)}\n\n`);
    expect(getDailyNoteHeading(date)).toMatch(/2026/);
  });
});

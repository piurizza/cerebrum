// Uses the default jsdom environment (see vite.config.ts) for
// `window.localStorage` -- this module writes to it directly, unlike
// src/lib/'s pure-logic tests that opt out of jsdom entirely.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { makeNoteMeta } from "../test/factories";

const mockListNotes = vi.fn();
const mockGetNote = vi.fn();
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    listNotes: () => mockListNotes(),
    getNote: (path: string) => mockGetNote(path),
  };
});

import { LAST_SYNCED_AT_KEY, syncVault } from "./sync";

beforeEach(() => {
  mockListNotes.mockReset();
  mockGetNote.mockReset();
  window.localStorage.clear();
  vi.spyOn(console, "warn").mockImplementation(() => {});
});

describe("syncVault", () => {
  it("fetches every note returned by listNotes so each is cached", async () => {
    const notes = [makeNoteMeta("a.md"), makeNoteMeta("b.md"), makeNoteMeta("c.md")];
    mockListNotes.mockResolvedValue(notes);
    mockGetNote.mockResolvedValue({
      path: "x",
      title: "x",
      tags: [],
      created: null,
      updated: null,
      content: "",
    });

    await syncVault();

    expect(mockGetNote).toHaveBeenCalledTimes(notes.length);
    for (const note of notes) {
      expect(mockGetNote).toHaveBeenCalledWith(note.path);
    }
  });

  it("does not throw and still fetches the rest when one note's fetch rejects", async () => {
    const notes = [makeNoteMeta("a.md"), makeNoteMeta("b.md"), makeNoteMeta("c.md")];
    mockListNotes.mockResolvedValue(notes);
    mockGetNote.mockImplementation((path: string) =>
      path === "b.md"
        ? Promise.reject(new Error("connection dropped"))
        : Promise.resolve({
            path,
            title: path,
            tags: [],
            created: null,
            updated: null,
            content: "",
          }),
    );

    await expect(syncVault()).resolves.toBeUndefined();

    expect(mockGetNote).toHaveBeenCalledTimes(notes.length);
    for (const note of notes) {
      expect(mockGetNote).toHaveBeenCalledWith(note.path);
    }
  });

  it("does not throw when listNotes itself fails, and leaves lastSyncedAt unset", async () => {
    mockListNotes.mockRejectedValue(new Error("network error"));

    await expect(syncVault()).resolves.toBeUndefined();

    expect(mockGetNote).not.toHaveBeenCalled();
    expect(window.localStorage.getItem(LAST_SYNCED_AT_KEY)).toBeNull();
  });

  it("persists a parseable ISO timestamp to localStorage on success", async () => {
    mockListNotes.mockResolvedValue([makeNoteMeta("a.md")]);
    mockGetNote.mockResolvedValue({
      path: "a.md",
      title: "a.md",
      tags: [],
      created: null,
      updated: null,
      content: "",
    });

    await syncVault();

    const stored = window.localStorage.getItem(LAST_SYNCED_AT_KEY);
    expect(stored).not.toBeNull();
    expect(Number.isNaN(new Date(stored as string).getTime())).toBe(false);
  });

  it("still persists lastSyncedAt even when some individual note fetches fail", async () => {
    mockListNotes.mockResolvedValue([makeNoteMeta("a.md"), makeNoteMeta("b.md")]);
    mockGetNote.mockImplementation((path: string) =>
      path === "b.md"
        ? Promise.reject(new Error("connection dropped"))
        : Promise.resolve({
            path,
            title: path,
            tags: [],
            created: null,
            updated: null,
            content: "",
          }),
    );

    await syncVault();

    expect(window.localStorage.getItem(LAST_SYNCED_AT_KEY)).not.toBeNull();
  });
});

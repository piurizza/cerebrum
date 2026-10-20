import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  loadVaultSettings,
  resetVaultFoldersForTests,
  VAULT_SETTINGS_KEY,
  vaultFolders,
  vaultLinkFormat,
} from "./vaultSettings";

const { mockGetVaultSettings } = vi.hoisted(() => ({ mockGetVaultSettings: vi.fn() }));
vi.mock("../api/client", () => ({ getVaultSettings: mockGetVaultSettings }));

const DEFAULTS = { dailyNoteFolder: "daily", templatesFolder: "templates" };

beforeEach(() => {
  window.localStorage.clear();
  resetVaultFoldersForTests();
  mockGetVaultSettings.mockReset();
});

afterEach(() => {
  window.localStorage.clear();
  resetVaultFoldersForTests();
});

describe("vaultFolders", () => {
  it("uses the defaults when the server has never been reached", () => {
    expect(vaultFolders()).toEqual(DEFAULTS);
  });

  it("uses the last values the server sent, before this session's load finishes", () => {
    window.localStorage.setItem(
      VAULT_SETTINGS_KEY,
      JSON.stringify({
        daily_note_folder: "journal",
        templates_folder: "meta/templates",
      }),
    );
    expect(vaultFolders()).toEqual({
      dailyNoteFolder: "journal",
      templatesFolder: "meta/templates",
    });
  });

  it("falls back to the defaults for a corrupt stored value", () => {
    window.localStorage.setItem(VAULT_SETTINGS_KEY, "{not json");
    expect(vaultFolders()).toEqual(DEFAULTS);
  });

  it("falls back per field for missing, non-string or slash-only stored values", () => {
    window.localStorage.setItem(
      VAULT_SETTINGS_KEY,
      JSON.stringify({ daily_note_folder: 42, templates_folder: "//" }),
    );
    expect(vaultFolders()).toEqual(DEFAULTS);
  });
});

describe("loadVaultSettings", () => {
  it("applies and remembers what the server sends", async () => {
    mockGetVaultSettings.mockResolvedValue({
      daily_note_folder: "journal/daily",
      templates_folder: "meta/templates",
    });

    await loadVaultSettings();

    expect(vaultFolders()).toEqual({
      dailyNoteFolder: "journal/daily",
      templatesFolder: "meta/templates",
    });
    resetVaultFoldersForTests();
    expect(vaultFolders().dailyNoteFolder).toBe("journal/daily");
  });

  it("trims slashes from what the server sends", async () => {
    mockGetVaultSettings.mockResolvedValue({
      daily_note_folder: "/journal/",
      templates_folder: "templates",
    });

    await loadVaultSettings();

    expect(vaultFolders().dailyNoteFolder).toBe("journal");
  });

  it("keeps the values in use when the server can't be reached", async () => {
    window.localStorage.setItem(
      VAULT_SETTINGS_KEY,
      JSON.stringify({ daily_note_folder: "journal", templates_folder: "templates" }),
    );
    mockGetVaultSettings.mockRejectedValue(new TypeError("Failed to fetch"));

    await expect(loadVaultSettings()).resolves.toBeUndefined();

    expect(vaultFolders().dailyNoteFolder).toBe("journal");
    expect(window.localStorage.getItem(VAULT_SETTINGS_KEY)).toContain("journal");
  });
});

describe("vaultLinkFormat", () => {
  it("is markdown until the server says otherwise", () => {
    expect(vaultLinkFormat()).toBe("markdown");
  });

  it("follows the server and remembers it", async () => {
    mockGetVaultSettings.mockResolvedValue({
      daily_note_folder: "daily",
      templates_folder: "templates",
      link_format: "wikilink",
    });

    await loadVaultSettings();

    expect(vaultLinkFormat()).toBe("wikilink");
    resetVaultFoldersForTests();
    expect(vaultLinkFormat()).toBe("wikilink");
  });

  it("treats a missing or unknown stored value as markdown", () => {
    window.localStorage.setItem(
      VAULT_SETTINGS_KEY,
      JSON.stringify({ link_format: "Wikilink" }),
    );
    expect(vaultLinkFormat()).toBe("markdown");
  });
});

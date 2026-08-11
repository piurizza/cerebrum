// @vitest-environment node
// Pure function, no DOM -- skip jsdom's window/document bootstrap cost.
import { describe, expect, it } from "vitest";
import { normalizeFolderEnvVar } from "./envFolder";

describe("normalizeFolderEnvVar", () => {
  it("falls back when the value is unset", () => {
    expect(normalizeFolderEnvVar(undefined, "daily")).toBe("daily");
  });

  it("falls back when the value is an explicit empty string", () => {
    // The `||`-not-`??` fix: a plausible `.env` typo (`FOO=`) must not
    // produce a leading-slash path.
    expect(normalizeFolderEnvVar("", "daily")).toBe("daily");
  });

  it("trims a trailing slash", () => {
    expect(normalizeFolderEnvVar("journal/", "daily")).toBe("journal");
  });

  it("trims a leading slash", () => {
    expect(normalizeFolderEnvVar("/journal", "daily")).toBe("journal");
  });

  it("falls back when the value is only slashes", () => {
    expect(normalizeFolderEnvVar("///", "daily")).toBe("daily");
  });

  it("passes a clean custom value through unchanged", () => {
    expect(normalizeFolderEnvVar("journal", "daily")).toBe("journal");
  });
});

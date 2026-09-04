import { afterEach, describe, expect, it } from "vitest";
import { setThemeColor } from "./themeColor";

function addThemeColorTags() {
  document.head.innerHTML = `
    <meta name="theme-color" content="#000000" />
    <meta name="theme-color" content="#111111" media="(prefers-color-scheme: light)" />
    <meta name="theme-color" content="#222222" media="(prefers-color-scheme: dark)" />
  `;
}

afterEach(() => {
  document.head.innerHTML = "";
});

describe("setThemeColor", () => {
  it("points every theme-color meta at the dark colour", () => {
    addThemeColorTags();
    setThemeColor("dark");
    const contents = [
      ...document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]'),
    ].map((m) => m.content);
    expect(contents).toEqual(["#26221d", "#26221d", "#26221d"]);
  });

  it("points every theme-color meta at the light colour", () => {
    addThemeColorTags();
    setThemeColor("light");
    const contents = [
      ...document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]'),
    ].map((m) => m.content);
    expect(contents).toEqual(["#f4ede0", "#f4ede0", "#f4ede0"]);
  });

  it("is a no-op (does not throw) when no theme-color meta exists", () => {
    expect(() => setThemeColor("dark")).not.toThrow();
  });
});

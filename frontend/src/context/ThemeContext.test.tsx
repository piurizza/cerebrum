import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { ThemeProvider, useTheme } from "./ThemeContext";

function Consumer() {
  const { theme, toggleTheme } = useTheme();
  return (
    <button type="button" onClick={toggleTheme}>
      {theme}
    </button>
  );
}

function themeColors(): string[] {
  return [
    ...document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]'),
  ].map((m) => m.content);
}

beforeEach(() => {
  document.head.innerHTML = `
    <meta name="theme-color" content="#000000" />
    <meta name="theme-color" content="#000000" media="(prefers-color-scheme: light)" />
    <meta name="theme-color" content="#000000" media="(prefers-color-scheme: dark)" />
  `;
  try {
    window.localStorage.clear();
  } catch {
    // storage may be unavailable in some runners -- the tests below don't rely on it
  }
});

afterEach(() => {
  document.head.innerHTML = "";
});

describe("ThemeProvider theme-color sync (U7)", () => {
  it("mounts without throwing (reads prefers-color-scheme via the matchMedia stub)", () => {
    expect(() => render(<Consumer />, { wrapper: ThemeProvider })).not.toThrow();
  });

  it("sets every theme-color meta to the current theme on mount", () => {
    render(<Consumer />, { wrapper: ThemeProvider });
    // The matchMedia stub reports no match -> osPreference() is "light".
    expect(themeColors()).toEqual(["#f4ede0", "#f4ede0", "#f4ede0"]);
  });

  it("updates every theme-color meta when the theme is toggled", async () => {
    render(<Consumer />, { wrapper: ThemeProvider });
    expect(screen.getByRole("button")).toHaveTextContent("light");

    await act(() => userEvent.click(screen.getByRole("button")));

    expect(screen.getByRole("button")).toHaveTextContent("dark");
    expect(themeColors()).toEqual(["#26221d", "#26221d", "#26221d"]);
  });
});

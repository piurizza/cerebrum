import type { ReactNode } from "react";
import { createContext, useCallback, useContext, useEffect, useState } from "react";

type Theme = "light" | "dark";

interface ThemeContextValue {
  theme: Theme;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

const STORAGE_KEY = "cerebrum-theme";

function initialTheme(): Theme {
  const stored = window.localStorage.getItem(STORAGE_KEY);
  if (stored === "light" || stored === "dark") return stored;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Manual per-device light/dark override, persisted across reloads (matches
 * the confirmed visual probe's theme toggle). Sets a `data-theme` attribute
 * on the document root; index.css pairs it with explicit
 * `:root[data-theme="light"|"dark"]` blocks that override every token to a
 * literal value -- a `[data-theme]` attribute selector on `:root` has
 * higher specificity than the bare `:root` rule that declares the
 * `light-dark()` defaults, so this deterministically wins regardless of OS
 * preference, independent of `color-scheme`/`light-dark()`'s own (less
 * battle-tested) override behavior. Still sets `color-scheme` too, so
 * native UA chrome (scrollbars, form controls) matches. Falls back to the
 * OS preference only on first load, before any explicit choice has been
 * stored -- once toggled, the explicit choice always wins, matching the
 * typical light/dark-toggle UX convention. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    window.localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme((current) => (current === "dark" ? "light" : "dark"));
  }, []);

  return (
    <ThemeContext.Provider value={{ theme, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme must be used within a ThemeProvider");
  }
  return context;
}

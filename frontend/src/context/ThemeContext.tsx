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
 * the confirmed visual probe's theme toggle). The app already switches
 * palette automatically via `color-scheme: light dark` + `light-dark()` in
 * index.css, driven by OS preference -- this adds an explicit override on
 * top rather than a second set of variables: setting `color-scheme` to a
 * single value (`light` or `dark`, not `light dark`) on the document root
 * makes every `light-dark()` token resolve to that branch regardless of OS
 * preference. Falls back to the OS preference only on first load, before
 * any explicit choice has been stored -- once toggled, the explicit choice
 * always wins, matching the typical light/dark-toggle UX convention. */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => {
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

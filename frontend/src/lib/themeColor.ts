type Theme = "light" | "dark";

const THEME_COLORS: Record<Theme, string> = {
  light: "#f4ede0",
  dark: "#26221d",
};

/**
 * Point every `<meta name="theme-color">` at the resolved theme's colour.
 *
 * `index.html` ships three such tags: a media-less one plus a
 * `prefers-color-scheme` light/dark pair. A given browser honours whichever
 * currently matches, and that isn't knowable here -- so the in-app toggle
 * (R11) has to win by overwriting *all* of them, media-qualified or not.
 * A no-op (never throws) when the document carries none.
 */
export function setThemeColor(theme: Theme): void {
  const color = THEME_COLORS[theme];
  const tags = document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]');
  for (const tag of tags) {
    tag.content = color;
  }
}

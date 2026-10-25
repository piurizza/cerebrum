import { useState, useSyncExternalStore } from "react";

/** The phone breakpoint, matching the single `@media (max-width: 768px)`
 * block in index.css. */
export const MOBILE_QUERY = "(max-width: 768px)";

/** Subscribes to a media query and re-renders on match changes. Reads
 * `window.matchMedia` once (captured on first render) so a test can swap
 * the implementation per-case before mounting. */
export function useMediaQuery(query: string): boolean {
  const [mql] = useState(() => window.matchMedia(query));
  return useSyncExternalStore(
    (onChange) => {
      mql.addEventListener("change", onChange);
      return () => mql.removeEventListener("change", onChange);
    },
    () => mql.matches,
    () => false,
  );
}

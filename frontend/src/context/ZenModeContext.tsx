import type { ReactNode } from "react";
import { createContext, useCallback, useContext, useState } from "react";

interface ZenModeContextValue {
  isZen: boolean;
  toggleZen: () => void;
}

const ZenModeContext = createContext<ZenModeContextValue | null>(null);

/** Per-session, opt-in distraction-free mode that collapses the sidebar
 * (R12). Lives in its own context (mirroring `NotesContext`'s shape)
 * because the sidebar it hides (`AppShell`'s `<aside>`) and the toggle
 * button (in `NoteViewPage`'s chrome row) are siblings, not parent/child
 * -- there's no single component both could share local state through.
 * Always starts `false` on mount -- the app never defaults into Zen
 * mode. */
export function ZenModeProvider({ children }: { children: ReactNode }) {
  const [isZen, setIsZen] = useState(false);
  const toggleZen = useCallback(() => setIsZen((current) => !current), []);

  return (
    <ZenModeContext.Provider value={{ isZen, toggleZen }}>
      {children}
    </ZenModeContext.Provider>
  );
}

export function useZenMode(): ZenModeContextValue {
  const context = useContext(ZenModeContext);
  if (!context) {
    throw new Error("useZenMode must be used within a ZenModeProvider");
  }
  return context;
}

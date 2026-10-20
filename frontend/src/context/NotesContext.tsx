import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { errorMessage, listNotes } from "../api/client";
import type { NoteMeta } from "../types/note";

interface NotesContextValue {
  notes: NoteMeta[];
  error: string | null;
  /** True until the initial `listNotes()` fetch settles (success or
   * failure). Consumers that decide "does this note already exist?"
   * from `notes` -- like the sidebar's "Today" button -- must gate on
   * this: `notes` starts as `[]`, so a decision made before the first
   * fetch settles can't distinguish "no notes yet" from "notes not
   * loaded yet", and would misclassify an existing note as absent. */
  loading: boolean;
  /** Returns the underlying fetch's promise so a caller that needs
   * `notes` to be genuinely current before proceeding -- e.g. the
   * "Today" button re-checking whether its own just-created note exists
   * -- can `await` it. Callers that don't care (the existing
   * fire-and-forget call sites) can still call it without awaiting. */
  refreshNotes: () => Promise<void>;
}

const NotesContext = createContext<NotesContextValue | null>(null);

export function NotesProvider({ children }: { children: ReactNode }) {
  const [notes, setNotes] = useState<NoteMeta[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const lastIssuedRequest = useRef(0);
  const lastAppliedRequest = useRef(0);

  // Applies a response only if no later-issued request has already been
  // applied. Two fetches can now overlap (a focus refresh and an explicit
  // refreshNotes() after a create), and an older response landing last
  // would otherwise roll the list back past the note just created. A
  // discarded response is never fresher than the one already applied, so
  // the "after `await refreshNotes()` the list is current" contract holds.
  const fetchNotes = useCallback(async (): Promise<void> => {
    lastIssuedRequest.current += 1;
    const request = lastIssuedRequest.current;
    const result = await listNotes();
    if (request < lastAppliedRequest.current) {
      return;
    }
    lastAppliedRequest.current = request;
    setNotes(result);
    setError(null);
  }, []);

  const refreshNotes = useCallback(async () => {
    try {
      await fetchNotes();
    } catch (err: unknown) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [fetchNotes]);

  useEffect(() => {
    refreshNotes();
  }, [refreshNotes]);

  // Notes written while this window was in the background (another
  // device, an MCP client, a file edited on disk) only reach the sidebar
  // through a fresh listNotes() -- there is no push channel. A
  // long-lived window (the desktop app, an installed PWA) never reloads,
  // so refetch when it comes back to the foreground. A failed background
  // refresh keeps the last good list instead of replacing the sidebar
  // with an error: the user didn't ask for it, and a wake-from-sleep
  // focus event commonly fires before the network is back.
  useEffect(() => {
    let inFlight = false;

    function refreshInBackground() {
      if (inFlight || document.visibilityState !== "visible") {
        return;
      }
      inFlight = true;
      fetchNotes()
        .catch((err: unknown) => {
          console.warn(`Background note refresh failed: ${errorMessage(err)}`);
        })
        .finally(() => {
          inFlight = false;
        });
    }

    window.addEventListener("focus", refreshInBackground);
    document.addEventListener("visibilitychange", refreshInBackground);
    return () => {
      window.removeEventListener("focus", refreshInBackground);
      document.removeEventListener("visibilitychange", refreshInBackground);
    };
  }, [fetchNotes]);

  return (
    <NotesContext.Provider value={{ notes, error, loading, refreshNotes }}>
      {children}
    </NotesContext.Provider>
  );
}

/** The vault's notes, or an empty list outside a `NotesProvider` -- for
 * components that only enrich their output with the note list (the
 * preview's wikilinks) and should still render without one. */
export function useNotesIfLoaded(): NoteMeta[] {
  return useContext(NotesContext)?.notes ?? [];
}

export function useNotes(): NotesContextValue {
  const context = useContext(NotesContext);
  if (!context) {
    throw new Error("useNotes must be used within a NotesProvider");
  }
  return context;
}

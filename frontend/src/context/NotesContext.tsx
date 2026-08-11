import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
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

  const refreshNotes = useCallback(async () => {
    try {
      const result = await listNotes();
      setNotes(result);
      setError(null);
    } catch (err: unknown) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refreshNotes();
  }, [refreshNotes]);

  return (
    <NotesContext.Provider value={{ notes, error, loading, refreshNotes }}>
      {children}
    </NotesContext.Provider>
  );
}

export function useNotes(): NotesContextValue {
  const context = useContext(NotesContext);
  if (!context) {
    throw new Error("useNotes must be used within a NotesProvider");
  }
  return context;
}

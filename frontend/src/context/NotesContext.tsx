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
  refreshNotes: () => void;
}

const NotesContext = createContext<NotesContextValue | null>(null);

export function NotesProvider({ children }: { children: ReactNode }) {
  const [notes, setNotes] = useState<NoteMeta[]>([]);
  const [error, setError] = useState<string | null>(null);

  const refreshNotes = useCallback(() => {
    listNotes()
      .then((result) => {
        setNotes(result);
        setError(null);
      })
      .catch((err: unknown) => setError(errorMessage(err)));
  }, []);

  useEffect(() => {
    refreshNotes();
  }, [refreshNotes]);

  return (
    <NotesContext.Provider value={{ notes, error, refreshNotes }}>
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

import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { encodeNotePath, putNote, searchNotes } from "../../api/client";
import { useNotes } from "../../context/NotesContext";
import { buildNoteTree } from "../../lib/noteTree";
import type { NoteMeta } from "../../types/note";
import { FolderPickerModal } from "../FolderPicker/FolderPickerModal";
import { NoteTreeList } from "./NoteTreeList";

const SEARCH_DEBOUNCE_MS = 250;

export function NoteBrowser() {
  const { notes, error, refreshNotes } = useNotes();
  const [isPickerOpen, setIsPickerOpen] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [collapsedFolders, setCollapsedFolders] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<NoteMeta[] | null>(null);
  const [searching, setSearching] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      setResults(null);
      setSearching(false);
      return;
    }
    setSearching(true);
    const handle = window.setTimeout(() => {
      searchNotes(trimmed)
        .then(setResults)
        .catch(() => setResults([]))
        .finally(() => setSearching(false));
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [query]);

  // Titles aren't unique -- two notes in different folders can share a
  // title. Only show the disambiguating path for titles that actually
  // collide, so the common case (unique titles) stays uncluttered.
  const duplicateTitles = useMemo(() => {
    const counts = new Map<string, number>();
    for (const note of notes) {
      counts.set(note.title, (counts.get(note.title) ?? 0) + 1);
    }
    return new Set(
      [...counts.entries()].filter(([, count]) => count > 1).map(([title]) => title),
    );
  }, [notes]);

  const tree = useMemo(() => buildNoteTree(notes), [notes]);
  const searchResultNodes = useMemo(
    () => (results ?? []).map((note) => ({ type: "note" as const, note })),
    [results],
  );

  function toggleFolder(folderPath: string) {
    setCollapsedFolders((current) => {
      const next = new Set(current);
      if (next.has(folderPath)) {
        next.delete(folderPath);
      } else {
        next.add(folderPath);
      }
      return next;
    });
  }

  async function handleCreate(path: string) {
    setCreateError(null);

    if (notes.some((note) => note.path === path)) {
      setCreateError(`A note already exists at "${path}".`);
      return;
    }

    try {
      await putNote(path, "");
    } catch (err) {
      setCreateError(String(err));
      return;
    }

    setIsPickerOpen(false);
    refreshNotes();
    navigate(`/notes/${encodeNotePath(path)}`);
  }

  if (error) {
    return (
      <p className="error-text" role="alert">
        Failed to load notes: {error}
      </p>
    );
  }

  return (
    <nav aria-label="Notes" className="note-browser">
      <button
        type="button"
        className="btn btn-block"
        onClick={() => {
          setCreateError(null);
          setIsPickerOpen(true);
        }}
      >
        + New note
      </button>
      {isPickerOpen && (
        <FolderPickerModal
          title="New note"
          initialPath=""
          confirmLabel="Create"
          error={createError}
          onConfirm={handleCreate}
          onCancel={() => setIsPickerOpen(false)}
        />
      )}
      <input
        type="search"
        className="search-input"
        placeholder="Search notes..."
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      {results !== null ? (
        searching ? (
          <p className="empty-hint">Searching...</p>
        ) : results.length === 0 ? (
          <p className="empty-hint">No matches for "{query.trim()}".</p>
        ) : (
          <NoteTreeList
            nodes={searchResultNodes}
            duplicateTitles={duplicateTitles}
            collapsedFolders={collapsedFolders}
            onToggleFolder={toggleFolder}
          />
        )
      ) : notes.length === 0 ? (
        <p className="empty-hint">No notes yet.</p>
      ) : (
        <NoteTreeList
          nodes={tree}
          duplicateTitles={duplicateTitles}
          collapsedFolders={collapsedFolders}
          onToggleFolder={toggleFolder}
        />
      )}
    </nav>
  );
}

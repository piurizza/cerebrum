import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { encodeNotePath, putNote } from "../../api/client";
import { useNotes } from "../../context/NotesContext";
import { buildNoteTree } from "../../lib/noteTree";
import { FolderPickerModal } from "../FolderPicker/FolderPickerModal";
import { NoteTreeList } from "./NoteTreeList";

export function NoteBrowser() {
  const { notes, error, refreshNotes } = useNotes();
  const [isPickerOpen, setIsPickerOpen] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [collapsedFolders, setCollapsedFolders] = useState<Set<string>>(new Set());
  const navigate = useNavigate();

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
      {notes.length === 0 ? (
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

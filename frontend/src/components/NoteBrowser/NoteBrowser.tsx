import { type FormEvent, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { encodeNotePath, putNote } from "../../api/client";
import { useNotes } from "../../context/NotesContext";
import { buildNoteTree } from "../../lib/noteTree";
import { NoteTreeList } from "./NoteTreeList";

function normalizeNotePath(input: string): string {
  const trimmed = input.trim();
  return trimmed.endsWith(".md") ? trimmed : `${trimmed}.md`;
}

export function NoteBrowser() {
  const { notes, error, refreshNotes } = useNotes();
  const [isCreating, setIsCreating] = useState(false);
  const [newPath, setNewPath] = useState("");
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

  function cancelCreate() {
    setIsCreating(false);
    setNewPath("");
    setCreateError(null);
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setCreateError(null);

    const path = normalizeNotePath(newPath);
    if (path === ".md") {
      setCreateError("Enter a name for the note.");
      return;
    }
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

    cancelCreate();
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
      {isCreating ? (
        <form onSubmit={handleCreate} className="new-note-form">
          <input
            type="text"
            placeholder="folder/note.md"
            value={newPath}
            onChange={(event) => setNewPath(event.target.value)}
          />
          <div className="new-note-actions">
            <button type="submit" className="btn btn-primary">
              Create
            </button>
            <button type="button" className="btn" onClick={cancelCreate}>
              Cancel
            </button>
          </div>
          {createError && (
            <p className="error-text" role="alert">
              {createError}
            </p>
          )}
        </form>
      ) : (
        <button
          type="button"
          className="btn btn-block"
          onClick={() => setIsCreating(true)}
        >
          + New note
        </button>
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

import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";
import { encodeNotePath, listNotes, putNote } from "../../api/client";
import type { NoteMeta } from "../../types/note";

function normalizeNotePath(input: string): string {
  const trimmed = input.trim();
  return trimmed.endsWith(".md") ? trimmed : `${trimmed}.md`;
}

export function NoteBrowser() {
  const [notes, setNotes] = useState<NoteMeta[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [newPath, setNewPath] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
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

  const refreshNotes = useCallback(() => {
    listNotes()
      .then(setNotes)
      .catch((err: unknown) => setError(String(err)));
  }, []);

  useEffect(() => {
    refreshNotes();
  }, [refreshNotes]);

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
        <ul className="note-list">
          {notes.map((note) => (
            <li key={note.path}>
              <NavLink
                to={`/notes/${encodeNotePath(note.path)}`}
                title={note.path}
                className={({ isActive }) =>
                  isActive ? "note-link is-active" : "note-link"
                }
              >
                <span className="note-title">{note.title}</span>
                {duplicateTitles.has(note.title) && (
                  <span className="note-path-hint">{note.path}</span>
                )}
              </NavLink>
            </li>
          ))}
        </ul>
      )}
    </nav>
  );
}

import { type FormEvent, useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
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
    return <p role="alert">Failed to load notes: {error}</p>;
  }

  return (
    <nav aria-label="Notes">
      {isCreating ? (
        <form onSubmit={handleCreate} className="new-note-form">
          <input
            type="text"
            placeholder="folder/note.md"
            value={newPath}
            onChange={(event) => setNewPath(event.target.value)}
          />
          <div className="new-note-actions">
            <button type="submit">Create</button>
            <button type="button" onClick={cancelCreate}>
              Cancel
            </button>
          </div>
          {createError && <p role="alert">{createError}</p>}
        </form>
      ) : (
        <button type="button" onClick={() => setIsCreating(true)}>
          + New note
        </button>
      )}
      <ul>
        {notes.map((note) => (
          <li key={note.path}>
            <Link to={`/notes/${encodeNotePath(note.path)}`}>{note.title}</Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

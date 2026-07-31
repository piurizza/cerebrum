import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { encodeNotePath, listNotes } from "../../api/client";
import type { NoteMeta } from "../../types/note";

export function NoteBrowser() {
  const [notes, setNotes] = useState<NoteMeta[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listNotes()
      .then(setNotes)
      .catch((err: unknown) => setError(String(err)));
  }, []);

  if (error) {
    return <p role="alert">Failed to load notes: {error}</p>;
  }

  return (
    <nav aria-label="Notes">
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

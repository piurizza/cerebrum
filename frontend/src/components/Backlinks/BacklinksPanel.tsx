import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { encodeNotePath, getBacklinks } from "../../api/client";
import type { NoteMeta } from "../../types/note";

interface BacklinksPanelProps {
  path: string;
}

export function BacklinksPanel({ path }: BacklinksPanelProps) {
  const [backlinks, setBacklinks] = useState<NoteMeta[]>([]);

  useEffect(() => {
    getBacklinks(path).then(setBacklinks).catch(console.error);
  }, [path]);

  if (backlinks.length === 0) {
    return <p className="empty-hint">No backlinks yet.</p>;
  }

  return (
    <ul className="note-list">
      {backlinks.map((note) => (
        <li key={note.path}>
          <Link className="note-link" to={`/notes/${encodeNotePath(note.path)}`}>
            {note.title}
          </Link>
        </li>
      ))}
    </ul>
  );
}

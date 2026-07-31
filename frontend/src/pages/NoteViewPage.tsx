import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { getNote, putNote } from "../api/client";
import { BacklinksPanel } from "../components/Backlinks/BacklinksPanel";
import { MarkdownEditor } from "../components/Editor/MarkdownEditor";

export function NoteViewPage() {
  const params = useParams();
  const path = params["*"] ?? "";
  const [content, setContent] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!path) return;
    setLoading(true);
    getNote(path)
      .then((note) => setContent(note.content))
      .finally(() => setLoading(false));
  }, [path]);

  if (!path) {
    return <p>Select a note from the sidebar.</p>;
  }

  if (loading) {
    return <p>Loading…</p>;
  }

  return (
    <div className="note-view">
      <div className="note-editor">
        <MarkdownEditor value={content} onChange={setContent} />
        <button type="button" onClick={() => putNote(path, content)}>
          Save
        </button>
      </div>
      <aside className="note-backlinks">
        <h2>Backlinks</h2>
        <BacklinksPanel path={path} />
      </aside>
    </div>
  );
}

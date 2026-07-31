import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { getNote, putNote } from "../api/client";
import { BacklinksPanel } from "../components/Backlinks/BacklinksPanel";
import { MarkdownEditor } from "../components/Editor/MarkdownEditor";

export function NoteViewPage() {
  const params = useParams();
  const path = params["*"] ?? "";
  const [content, setContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!path) return;
    setLoading(true);
    getNote(path)
      .then((note) => {
        setContent(note.content);
        setSavedContent(note.content);
      })
      .finally(() => setLoading(false));
  }, [path]);

  async function handleSave() {
    setSaving(true);
    try {
      const note = await putNote(path, content);
      setSavedContent(note.content);
      setContent(note.content);
    } finally {
      setSaving(false);
    }
  }

  if (!path) {
    return (
      <p className="empty-hint">Select a note from the sidebar, or create a new one.</p>
    );
  }

  if (loading) {
    return <p className="empty-hint">Loading...</p>;
  }

  const isDirty = content !== savedContent;

  return (
    <div className="note-view">
      <div className="note-editor">
        <MarkdownEditor value={content} onChange={setContent} />
        <div className="note-editor-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleSave}
            disabled={saving}
          >
            {saving ? "Saving..." : "Save"}
          </button>
          <span className="save-status">{isDirty ? "Unsaved changes" : "Saved"}</span>
        </div>
      </div>
      <aside className="note-backlinks">
        <h2>Backlinks</h2>
        <BacklinksPanel path={path} />
      </aside>
    </div>
  );
}

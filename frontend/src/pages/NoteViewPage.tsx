import { useCallback, useEffect, useState } from "react";
import { useBlocker, useNavigate, useParams } from "react-router-dom";
import { encodeNotePath, errorMessage, getNote, putNote } from "../api/client";
import { BacklinksPanel } from "../components/Backlinks/BacklinksPanel";
import { UnsavedChangesDialog } from "../components/ConfirmDialog/UnsavedChangesDialog";
import { MarkdownEditor } from "../components/Editor/MarkdownEditor";
import { MarkdownPreview } from "../components/Editor/MarkdownPreview";
import { NotePathHeader } from "../components/Editor/NotePathHeader";
import { stripFrontmatter } from "../lib/noteContent";

type ViewMode = "edit" | "preview";

export function NoteViewPage() {
  const params = useParams();
  const path = params["*"] ?? "";
  const navigate = useNavigate();
  const [content, setContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [title, setTitle] = useState("");
  const [created, setCreated] = useState<string | null>(null);
  const [updated, setUpdated] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [mode, setMode] = useState<ViewMode>("preview");
  const [blockerError, setBlockerError] = useState<string | null>(null);

  useEffect(() => {
    if (!path) return;
    setLoading(true);
    setMode("preview");
    getNote(path)
      .then((note) => {
        setContent(note.content);
        setSavedContent(note.content);
        setTitle(note.title);
        setCreated(note.created);
        setUpdated(note.updated);
      })
      .finally(() => setLoading(false));
  }, [path]);

  const isDirty = content !== savedContent;

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      const note = await putNote(path, content);
      setSavedContent(note.content);
      setContent(note.content);
      setUpdated(note.updated);
    } finally {
      setSaving(false);
    }
  }, [path, content]);

  useEffect(() => {
    if (!path) return;
    function handleKeyDown(event: KeyboardEvent) {
      const isSaveShortcut =
        (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s";
      if (!isSaveShortcut) return;
      event.preventDefault();
      if (!saving) handleSave();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [path, saving, handleSave]);

  // Warns on tab close/refresh (R2) -- browsers only allow a native,
  // unstyled confirmation here, no custom Save/Discard/Cancel UI is
  // possible (KTD3), unlike the router-navigation case below.
  useEffect(() => {
    function handleBeforeUnload(event: BeforeUnloadEvent) {
      if (!isDirty) return;
      event.preventDefault();
    }
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [isDirty]);

  // Intercepts every router-mediated navigation away from a dirty note --
  // sidebar clicks, note-to-note links, graph node clicks, browser
  // back/forward -- regardless of which component triggered it, since
  // useBlocker fires on any attempted route change while this component
  // is mounted (KTD2). Requires the data router migration (KTD1).
  const blocker = useBlocker(isDirty);

  async function handleBlockedSave() {
    setBlockerError(null);
    try {
      await handleSave();
      if (blocker.state === "blocked") blocker.proceed();
    } catch (err) {
      // handleSave's own finally already reset `saving` -- only the
      // dialog's error state is this function's responsibility. Do NOT
      // proceed(): the edit must stay on this note until Save succeeds,
      // Discard is chosen, or Cancel is chosen (R3).
      setBlockerError(errorMessage(err));
    }
  }

  function handleBlockedDiscard() {
    setBlockerError(null);
    if (blocker.state === "blocked") blocker.proceed();
  }

  function handleBlockedCancel() {
    setBlockerError(null);
    if (blocker.state === "blocked") blocker.reset();
  }

  if (!path) {
    return (
      <p className="empty-hint">Select a note from the sidebar, or create a new one.</p>
    );
  }

  if (loading) {
    return <p className="empty-hint">Loading...</p>;
  }

  return (
    <div className="note-view">
      {blocker.state === "blocked" && (
        <UnsavedChangesDialog
          error={blockerError}
          busy={saving}
          onSave={handleBlockedSave}
          onDiscard={handleBlockedDiscard}
          onCancel={handleBlockedCancel}
        />
      )}
      <div className="note-editor">
        <NotePathHeader
          path={path}
          title={title}
          created={created}
          updated={updated}
          onRenamed={(updatedNote) => {
            setContent(updatedNote.content);
            setSavedContent(updatedNote.content);
            setTitle(updatedNote.title);
            setUpdated(updatedNote.updated);
            if (updatedNote.path !== path) {
              navigate(`/notes/${encodeNotePath(updatedNote.path)}`);
            }
          }}
          onDeleted={() => navigate("/")}
        />
        <div className="mode-toggle" role="tablist" aria-label="Editor mode">
          <button
            type="button"
            role="tab"
            aria-selected={mode === "edit"}
            className={mode === "edit" ? "btn btn-toggle is-active" : "btn btn-toggle"}
            onClick={() => setMode("edit")}
          >
            Edit
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "preview"}
            className={
              mode === "preview" ? "btn btn-toggle is-active" : "btn btn-toggle"
            }
            onClick={() => setMode("preview")}
          >
            Preview
          </button>
        </div>

        {mode === "edit" ? (
          <MarkdownEditor value={content} onChange={setContent} currentPath={path} />
        ) : (
          <MarkdownPreview body={stripFrontmatter(content)} currentPath={path} />
        )}

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

import { type FormEvent, useState } from "react";
import { deleteNote, errorMessage, moveNote } from "../../api/client";
import { useNotes } from "../../context/NotesContext";
import { formatTimestamp } from "../../lib/formatDate";
import type { Note } from "../../types/note";
import { FolderPickerModal } from "../FolderPicker/FolderPickerModal";

interface NotePathHeaderProps {
  path: string;
  title: string;
  created: string | null;
  updated: string | null;
  onRenamed: (updated: Note) => void;
  onDeleted: () => void;
}

export function NotePathHeader({
  path,
  title,
  created,
  updated,
  onRenamed,
  onDeleted,
}: NotePathHeaderProps) {
  const { notes, refreshNotes } = useNotes();
  const [copied, setCopied] = useState(false);
  const [isRenaming, setIsRenaming] = useState(false);
  const [isPickerOpen, setIsPickerOpen] = useState(false);
  const [newPath, setNewPath] = useState(path);
  const [newTitle, setNewTitle] = useState(title);
  const [renaming, setRenaming] = useState(false);
  const [renameError, setRenameError] = useState<string | null>(null);
  const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  async function handleCopy() {
    await navigator.clipboard.writeText(path);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  function startRename() {
    setNewPath(path);
    setNewTitle(title);
    setRenameError(null);
    setIsRenaming(true);
  }

  function cancelRename() {
    setIsRenaming(false);
    setRenameError(null);
  }

  async function handleRename(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setRenameError(null);

    const target = newPath;
    const trimmedTitle = newTitle.trim();
    const pathChanged = target !== path;
    const titleChanged = trimmedTitle !== title && trimmedTitle !== "";

    if (!pathChanged && !titleChanged) {
      setIsRenaming(false);
      return;
    }
    if (pathChanged && notes.some((note) => note.path === target)) {
      setRenameError(`A note already exists at "${target}".`);
      return;
    }

    setRenaming(true);
    try {
      const updated = await moveNote(
        path,
        target,
        titleChanged ? trimmedTitle : undefined,
      );
      setRenaming(false);
      setIsRenaming(false);
      refreshNotes();
      onRenamed(updated);
    } catch (err) {
      setRenameError(errorMessage(err));
      setRenaming(false);
    }
  }

  async function handleDelete() {
    setDeleteError(null);
    setDeleting(true);
    try {
      await deleteNote(path);
    } catch (err) {
      setDeleteError(errorMessage(err));
      setDeleting(false);
      return;
    }
    refreshNotes();
    onDeleted();
  }

  if (isConfirmingDelete) {
    return (
      <div className="note-path-header delete-confirm">
        <span>Delete this note? This can't be undone.</span>
        <button
          type="button"
          className="btn btn-danger"
          onClick={handleDelete}
          disabled={deleting}
        >
          {deleting ? "Deleting..." : "Delete"}
        </button>
        <button
          type="button"
          className="btn"
          onClick={() => setIsConfirmingDelete(false)}
          disabled={deleting}
        >
          Cancel
        </button>
        {deleteError && (
          <p className="error-text rename-error" role="alert">
            {deleteError}
          </p>
        )}
      </div>
    );
  }

  if (isRenaming) {
    return (
      <>
        <form onSubmit={handleRename} className="rename-form">
          <div className="rename-field">
            Path
            <div className="path-picker-trigger">
              <code className="note-path">{newPath}</code>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => setIsPickerOpen(true)}
              >
                Choose location
              </button>
            </div>
          </div>
          <label className="rename-field">
            Title
            <input
              type="text"
              value={newTitle}
              onChange={(event) => setNewTitle(event.target.value)}
            />
          </label>
          <button type="submit" className="btn btn-primary" disabled={renaming}>
            {renaming ? "Renaming..." : "Rename"}
          </button>
          <button type="button" className="btn" onClick={cancelRename}>
            Cancel
          </button>
          {renameError && (
            <p className="error-text rename-error" role="alert">
              {renameError}
            </p>
          )}
        </form>
        {isPickerOpen && (
          <FolderPickerModal
            title="Move note"
            initialPath={newPath}
            confirmLabel="Select"
            onConfirm={(selected) => {
              setNewPath(selected);
              setIsPickerOpen(false);
            }}
            onCancel={() => setIsPickerOpen(false)}
          />
        )}
      </>
    );
  }

  const createdLabel = formatTimestamp(created);
  const updatedLabel = formatTimestamp(updated);

  return (
    <>
      <div className="note-path-header">
        <code className="note-path">{path}</code>
        <button type="button" className="btn btn-sm" onClick={handleCopy}>
          {copied ? "Copied!" : "Copy path"}
        </button>
        <button type="button" className="btn btn-sm" onClick={startRename}>
          Rename
        </button>
        <button
          type="button"
          className="btn btn-sm btn-danger-outline"
          onClick={() => setIsConfirmingDelete(true)}
        >
          Delete
        </button>
      </div>
      {(createdLabel || updatedLabel) && (
        <p className="note-meta">
          {createdLabel && <span>Created {createdLabel}</span>}
          {createdLabel && updatedLabel && <span className="note-meta-sep">·</span>}
          {updatedLabel && <span>Updated {updatedLabel}</span>}
        </p>
      )}
    </>
  );
}

import { type FormEvent, useState } from "react";
import { moveNote } from "../../api/client";
import { useNotes } from "../../context/NotesContext";

interface NotePathHeaderProps {
  path: string;
  onRenamed: (newPath: string) => void;
}

function normalizeNotePath(input: string): string {
  const trimmed = input.trim();
  return trimmed.endsWith(".md") ? trimmed : `${trimmed}.md`;
}

export function NotePathHeader({ path, onRenamed }: NotePathHeaderProps) {
  const { notes, refreshNotes } = useNotes();
  const [copied, setCopied] = useState(false);
  const [isRenaming, setIsRenaming] = useState(false);
  const [newPath, setNewPath] = useState(path);
  const [renaming, setRenaming] = useState(false);
  const [renameError, setRenameError] = useState<string | null>(null);

  async function handleCopy() {
    await navigator.clipboard.writeText(path);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  function startRename() {
    setNewPath(path);
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

    const target = normalizeNotePath(newPath);
    if (target === path) {
      setIsRenaming(false);
      return;
    }
    if (notes.some((note) => note.path === target)) {
      setRenameError(`A note already exists at "${target}".`);
      return;
    }

    setRenaming(true);
    try {
      await moveNote(path, target);
    } catch (err) {
      setRenameError(String(err));
      setRenaming(false);
      return;
    }
    setRenaming(false);
    setIsRenaming(false);
    refreshNotes();
    onRenamed(target);
  }

  if (isRenaming) {
    return (
      <form onSubmit={handleRename} className="rename-form">
        <input
          type="text"
          value={newPath}
          onChange={(event) => setNewPath(event.target.value)}
        />
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
    );
  }

  return (
    <div className="note-path-header">
      <code className="note-path">{path}</code>
      <button type="button" className="btn btn-copy" onClick={handleCopy}>
        {copied ? "Copied!" : "Copy path"}
      </button>
      <button type="button" className="btn btn-copy" onClick={startRename}>
        Rename
      </button>
    </div>
  );
}

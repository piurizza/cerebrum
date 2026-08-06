import { type FormEvent, useEffect, useRef, useState } from "react";
import { useNotes } from "../../context/NotesContext";
import { useFocusTrap } from "../../hooks/useFocusTrap";
import {
  childFolderNames,
  collectFolderPaths,
  joinNotePath,
  splitNotePath,
} from "../../lib/noteTree";

interface FolderPickerModalProps {
  title: string;
  initialPath: string;
  confirmLabel: string;
  error?: string | null;
  onConfirm: (path: string) => void;
  onCancel: () => void;
}

function normalizeFilename(input: string): string {
  const trimmed = input.trim();
  return trimmed.endsWith(".md") ? trimmed : `${trimmed}.md`;
}

export function FolderPickerModal({
  title,
  initialPath,
  confirmLabel,
  error,
  onConfirm,
  onCancel,
}: FolderPickerModalProps) {
  const { notes } = useNotes();
  const initial = splitNotePath(initialPath);
  const [currentFolder, setCurrentFolder] = useState(initial.folder);
  const [filename, setFilename] = useState(initial.filename);
  const [isAddingFolder, setIsAddingFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState("");
  const newFolderInputRef = useRef<HTMLInputElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);
  useFocusTrap(modalRef, true);

  const allFolders = collectFolderPaths(notes);
  const subfolders = childFolderNames(allFolders, currentFolder);
  const breadcrumbs = currentFolder ? currentFolder.split("/") : [];

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onCancel();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onCancel]);

  useEffect(() => {
    if (isAddingFolder) newFolderInputRef.current?.focus();
  }, [isAddingFolder]);

  function goToBreadcrumb(index: number) {
    setCurrentFolder(breadcrumbs.slice(0, index + 1).join("/"));
  }

  function addFolder(event: FormEvent) {
    event.preventDefault();
    const trimmed = newFolderName.trim();
    if (!trimmed) return;
    setCurrentFolder(joinNotePath(currentFolder, trimmed));
    setNewFolderName("");
    setIsAddingFolder(false);
  }

  function handleConfirm(event: FormEvent) {
    event.preventDefault();
    if (!filename.trim()) return;
    onConfirm(joinNotePath(currentFolder, normalizeFilename(filename)));
  }

  return (
    <div className="modal-overlay">
      <button
        type="button"
        className="modal-backdrop"
        aria-label="Close dialog"
        onClick={onCancel}
      />
      <div
        ref={modalRef}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <h2 className="modal-title">{title}</h2>

        <div className="folder-breadcrumbs">
          <button
            type="button"
            className="breadcrumb"
            onClick={() => setCurrentFolder("")}
          >
            Root
          </button>
          {breadcrumbs.map((segment, index) => (
            <span key={breadcrumbs.slice(0, index + 1).join("/")}>
              <span className="breadcrumb-sep">/</span>
              <button
                type="button"
                className="breadcrumb"
                onClick={() => goToBreadcrumb(index)}
              >
                {segment}
              </button>
            </span>
          ))}
        </div>

        <ul className="folder-picker-list">
          {subfolders.map((name) => (
            <li key={name}>
              <button
                type="button"
                className="folder-picker-entry"
                onClick={() => setCurrentFolder(joinNotePath(currentFolder, name))}
              >
                <span className="folder-caret is-expanded">▸</span>
                {name}
              </button>
            </li>
          ))}
          {subfolders.length === 0 && !isAddingFolder && (
            <li className="empty-hint folder-picker-empty">No subfolders here.</li>
          )}
        </ul>

        {isAddingFolder ? (
          <form onSubmit={addFolder} className="new-folder-form">
            <input
              ref={newFolderInputRef}
              type="text"
              placeholder="Folder name"
              value={newFolderName}
              onChange={(event) => setNewFolderName(event.target.value)}
            />
            <button type="submit" className="btn">
              Add
            </button>
            <button
              type="button"
              className="btn"
              onClick={() => setIsAddingFolder(false)}
            >
              Cancel
            </button>
          </form>
        ) : (
          <button
            type="button"
            className="btn btn-copy"
            onClick={() => setIsAddingFolder(true)}
          >
            + New folder
          </button>
        )}

        <form onSubmit={handleConfirm} className="modal-footer">
          <label className="rename-field">
            File name
            <input
              type="text"
              placeholder="note.md"
              value={filename}
              onChange={(event) => setFilename(event.target.value)}
            />
          </label>
          <div className="modal-actions">
            <button
              type="submit"
              className="btn btn-primary"
              disabled={!filename.trim()}
            >
              {confirmLabel}
            </button>
            <button type="button" className="btn" onClick={onCancel}>
              Cancel
            </button>
          </div>
          {error && (
            <p className="error-text rename-error" role="alert">
              {error}
            </p>
          )}
        </form>
      </div>
    </div>
  );
}

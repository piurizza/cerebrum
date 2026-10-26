import { useEffect, useRef, useState } from "react";
import { useFocusTrap } from "../../hooks/useFocusTrap";

interface SaveConflictDialogProps {
  error?: string | null;
  busy?: boolean;
  /** Disables both choices while a write or fetch can't reach the server;
   * Cancel stays, since it touches nothing. */
  isOffline?: boolean;
  onReload: () => void;
  onKeepMine: () => void;
  onCancel: () => void;
}

/** Shown when a save was refused because the note changed elsewhere and
 * the change overlaps the unsaved edits, so no automatic merge was
 * possible (R16). Each choice says what it throws away. Same
 * overlay/backdrop/Escape structure as `UnsavedChangesDialog`; Escape maps
 * to Cancel, which leaves the buffer as it is, unsaved. */
export function SaveConflictDialog({
  error,
  busy,
  isOffline = false,
  onReload,
  onKeepMine,
  onCancel,
}: SaveConflictDialogProps) {
  const modalRef = useRef<HTMLDivElement>(null);
  const isTopmost = useFocusTrap(modalRef, true);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      // Gated on `busy` and isTopmost for the same reasons as
      // UnsavedChangesDialog's own Escape handler.
      if (event.key === "Escape" && !busy && isTopmost) onCancel();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onCancel, busy, isTopmost]);

  return (
    <div className="modal-overlay">
      <button
        type="button"
        className="modal-backdrop"
        aria-label="Close dialog"
        onClick={onCancel}
        disabled={busy}
      />
      <div
        ref={modalRef}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label="This note changed"
      >
        <h2 className="modal-title">This note changed</h2>
        <p>
          The note was changed somewhere else since you opened it, and those changes
          touch the same lines as your unsaved edits.
        </p>
        <ul className="save-conflict-choices">
          <li>
            <strong>Reload</strong> opens the note as it is now and discards your
            unsaved edits from the editor. Your text stays on screen to copy.
          </li>
          <li>
            <strong>Keep mine</strong> saves your version over the note and discards the
            other changes.
          </li>
        </ul>
        <div className="modal-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={onReload}
            disabled={busy || isOffline}
          >
            Reload
          </button>
          <button
            type="button"
            className="btn btn-danger-outline"
            onClick={onKeepMine}
            disabled={busy || isOffline}
          >
            Keep mine
          </button>
          <button type="button" className="btn" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
        </div>
        {error && (
          <p className="error-text rename-error" role="alert">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}

interface UnsavedTextPanelProps {
  text: string;
  onDismiss: () => void;
}

/** After a Reload, the edits it took out of the editor: read-only, so it
 * can't be mistaken for the note, and selectable or copyable whole until
 * dismissed (R16). */
export function UnsavedTextPanel({ text, onDismiss }: UnsavedTextPanelProps) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    await navigator.clipboard.writeText(text);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <section className="unsaved-text">
      <h2 className="unsaved-text-title">Your unsaved text</h2>
      <p>The note was reloaded. Copy anything you still need before dismissing this.</p>
      <textarea
        className="unsaved-text-body"
        aria-label="Your unsaved text"
        value={text}
        readOnly
        rows={8}
      />
      <div className="modal-actions">
        <button type="button" className="btn btn-sm" onClick={handleCopy}>
          {copied ? "Copied!" : "Copy"}
        </button>
        <button type="button" className="btn btn-sm" onClick={onDismiss}>
          Dismiss
        </button>
      </div>
    </section>
  );
}

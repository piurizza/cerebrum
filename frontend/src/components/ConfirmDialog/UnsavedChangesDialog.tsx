import { useEffect, useRef } from "react";
import { useFocusTrap } from "../../hooks/useFocusTrap";

interface UnsavedChangesDialogProps {
  error?: string | null;
  busy?: boolean;
  onSave: () => void;
  onDiscard: () => void;
  onCancel: () => void;
}

/** Shown when navigating away from a note with unsaved edits (R1) --
 * mirrors `ConfirmDialog`'s overlay/backdrop/Escape-key structure (KTD4)
 * but with a third action, since Save/Discard/Cancel doesn't fit
 * `ConfirmDialog`'s two-button confirm/cancel shape without a breaking
 * prop change for its existing callers (`SettingsPage`'s token/account
 * flows). Escape maps to Cancel -- the non-destructive option, consistent
 * with Escape's existing meaning on every other modal in the app. */
export function UnsavedChangesDialog({
  error,
  busy,
  onSave,
  onDiscard,
  onCancel,
}: UnsavedChangesDialogProps) {
  const modalRef = useRef<HTMLDivElement>(null);
  useFocusTrap(modalRef, true);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onCancel();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onCancel]);

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
        aria-label="Unsaved changes"
      >
        <h2 className="modal-title">Unsaved changes</h2>
        <p>This note has unsaved changes. Save them before leaving?</p>
        <div className="modal-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={onSave}
            disabled={busy}
          >
            {busy ? "Saving..." : "Save"}
          </button>
          <button
            type="button"
            className="btn btn-danger-outline"
            onClick={onDiscard}
            disabled={busy}
          >
            Discard
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

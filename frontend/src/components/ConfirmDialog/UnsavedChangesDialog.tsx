import { useEffect, useRef } from "react";
import { useFocusTrap } from "../../hooks/useFocusTrap";

interface UnsavedChangesDialogProps {
  error?: string | null;
  busy?: boolean;
  /** Disables only the Save action (a network write) while offline, same
   * as every other write entry point in NoteViewPage -- Discard/Cancel
   * stay available since neither touches the network (review finding #8,
   * 2026-08-31 code review: this dialog's Save was the one write path
   * that had never been gated on isOffline). Defaults to `false`. */
  isOffline?: boolean;
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
  isOffline = false,
  onSave,
  onDiscard,
  onCancel,
}: UnsavedChangesDialogProps) {
  const modalRef = useRef<HTMLDivElement>(null);
  const isTopmost = useFocusTrap(modalRef, true);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      // Gated on `busy` like the three action buttons below: Cancel calls
      // blocker.reset() unconditionally, which would unmount this dialog
      // out from under an in-flight save -- its eventual failure would
      // then have nowhere to surface (setBlockerError firing into an
      // already-unmounted component). Also gated on isTopmost: this dialog
      // can stack on top of FolderPickerModal (dirty note -> Rename ->
      // Choose location -> browser Back), and a single Escape should only
      // cancel whichever one is actually in view (see useFocusTrap's
      // module-level comment).
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
        aria-label="Unsaved changes"
      >
        <h2 className="modal-title">Unsaved changes</h2>
        <p>This note has unsaved changes. Save them before leaving?</p>
        <div className="modal-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={onSave}
            disabled={busy || isOffline}
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

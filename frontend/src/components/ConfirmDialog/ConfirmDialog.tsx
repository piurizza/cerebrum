import { useEffect, useRef } from "react";
import { useFocusTrap } from "../../hooks/useFocusTrap";

interface ConfirmDialogProps {
  title: string;
  message: string;
  confirmLabel: string;
  error?: string | null;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/** A generic irreversible-action confirmation dialog, mirroring
 * `FolderPickerModal`'s modal-overlay/modal-backdrop structure and its
 * Escape-key handling -- this codebase's one established modal pattern,
 * reused here rather than inventing a second one. Used by `SettingsPage`
 * for revoking a personal API token and deactivating an account, both
 * immediately effective and irreversible. */
export function ConfirmDialog({
  title,
  message,
  confirmLabel,
  error,
  busy,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const modalRef = useRef<HTMLDivElement>(null);
  const isTopmost = useFocusTrap(modalRef, true);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      // Gated on isTopmost: if another modal is stacked on top of this one,
      // a single Escape press should cancel only the one actually in view,
      // not both at once (see useFocusTrap's module-level comment).
      if (event.key === "Escape" && isTopmost) onCancel();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onCancel, isTopmost]);

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
        <p>{message}</p>
        <div className="modal-actions">
          <button
            type="button"
            className="btn btn-danger"
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? "Working..." : confirmLabel}
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

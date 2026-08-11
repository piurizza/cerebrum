import { useEffect, useRef, useState } from "react";
import { useFocusTrap } from "../../hooks/useFocusTrap";
import type { TemplateOption, TemplateTier } from "../../lib/templates";

interface TemplatePickerModalProps {
  title: string;
  options: TemplateOption[];
  pending: boolean;
  error?: string | null;
  onConfirm: (templatePath: string | null) => void;
  onCancel: () => void;
}

const TIER_SECTIONS: { tier: TemplateTier; label: string }[] = [
  { tier: "matching-scope", label: "Suggested for this folder" },
  { tier: "global", label: "Templates" },
  { tier: "other-scope", label: "Other templates" },
];

const BLANK_VALUE = "";

function optionLabel(option: TemplateOption): string {
  return option.scope ? `${option.name} (${option.scope})` : option.name;
}

/** Offers "Blank note" (pre-selected, R5) plus every candidate template,
 * grouped by tier. Opened by `NoteBrowser` only when at least one relevant
 * template exists for the target folder -- see `hasRelevantTemplate` in
 * `lib/templates.ts`. Mirrors `FolderPickerModal`'s modal structure and
 * `ConfirmDialog`'s `pending`/`error` prop conventions (this codebase's
 * one established modal pattern) rather than inventing a new one --
 * except every dismiss path (Cancel, backdrop, Escape) disables while
 * `pending`, not just the buttons: confirming here starts an
 * uncancellable fetch-then-write-then-navigate chain, so a dismiss that
 * "succeeded" while it was still running would let the note get created
 * and the app navigate away anyway once it resolved. */
export function TemplatePickerModal({
  title,
  options,
  pending,
  error,
  onConfirm,
  onCancel,
}: TemplatePickerModalProps) {
  const [selected, setSelected] = useState(BLANK_VALUE);
  const modalRef = useRef<HTMLDivElement>(null);
  const isTopmost = useFocusTrap(modalRef, true);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      // Gated on isTopmost, same reasoning as FolderPickerModal/ConfirmDialog.
      // Also gated on `pending` -- unlike ConfirmDialog's confirm actions
      // (a single DELETE-style call), confirming here kicks off a
      // fetch-then-write-then-navigate chain with nothing to cancel it;
      // letting Escape dismiss mid-flight would let the user "cancel" while
      // the note still gets created and the app still navigates out from
      // under them once the chain resolves. Disabling every dismiss path
      // during `pending` (matching the Confirm/Cancel buttons) closes that
      // off entirely instead of adding a cancellation-token mechanism.
      if (event.key === "Escape" && isTopmost && !pending) onCancel();
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [onCancel, isTopmost, pending]);

  function handleConfirm() {
    onConfirm(selected === BLANK_VALUE ? null : selected);
  }

  return (
    <div className="modal-overlay">
      <button
        type="button"
        className="modal-backdrop"
        aria-label="Close dialog"
        onClick={pending ? undefined : onCancel}
      />
      <div
        ref={modalRef}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <h2 className="modal-title">{title}</h2>

        <fieldset className="template-picker-options" aria-label="Template">
          <label className="template-picker-option">
            <input
              type="radio"
              name="template-option"
              value={BLANK_VALUE}
              checked={selected === BLANK_VALUE}
              onChange={() => setSelected(BLANK_VALUE)}
              disabled={pending}
            />
            Blank note
          </label>

          {TIER_SECTIONS.map(({ tier, label }) => {
            const tierOptions = options.filter((option) => option.tier === tier);
            if (tierOptions.length === 0) return null;
            return (
              <div key={tier} className="template-picker-tier">
                <p className="template-picker-tier-label">{label}</p>
                {tierOptions.map((option) => (
                  <label key={option.path} className="template-picker-option">
                    <input
                      type="radio"
                      name="template-option"
                      value={option.path}
                      checked={selected === option.path}
                      onChange={() => setSelected(option.path)}
                      disabled={pending}
                    />
                    {optionLabel(option)}
                  </label>
                ))}
              </div>
            );
          })}
        </fieldset>

        <div className="modal-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleConfirm}
            disabled={pending}
          >
            {pending ? "Creating…" : "Create note"}
          </button>
          <button type="button" className="btn" onClick={onCancel} disabled={pending}>
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

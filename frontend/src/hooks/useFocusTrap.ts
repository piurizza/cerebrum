import type { RefObject } from "react";
import { useEffect } from "react";

const FOCUSABLE_SELECTOR =
  '[href], button, input, select, textarea, [tabindex]:not([tabindex="-1"])';

/** Traps Tab/Shift+Tab focus cycling within `containerRef`'s own focusable
 * elements while `active` is true: focuses the container's first
 * focusable element on activation, wraps Tab at the ends so focus never
 * reaches an element behind the modal, and restores focus to whatever
 * triggered the modal once it deactivates or unmounts -- the standard
 * modal keyboard-accessibility contract (R5). Used by `ConfirmDialog`,
 * `FolderPickerModal`, and `UnsavedChangesDialog`. */
export function useFocusTrap(
  containerRef: RefObject<HTMLElement | null>,
  active: boolean,
): void {
  useEffect(() => {
    if (!active) return;

    const trigger = document.activeElement as HTMLElement | null;

    function focusableElements(): HTMLElement[] {
      const container = containerRef.current;
      return container
        ? Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
        : [];
    }

    focusableElements()[0]?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key !== "Tab") return;
      const elements = focusableElements();
      if (elements.length === 0) return;
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      trigger?.focus();
    };
  }, [active, containerRef]);
}

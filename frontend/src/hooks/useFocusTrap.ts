import type { RefObject } from "react";
import { useEffect, useState, useSyncExternalStore } from "react";

// `:not(:disabled)` matters: ConfirmDialog and UnsavedChangesDialog both set
// disabled={busy} on every action button at once while a request is in
// flight, so without this exclusion `first`/`last` below can be a disabled
// element that can never become document.activeElement -- the wraparound
// check then never matches, and Tab silently escapes the trap during
// exactly the window a user is most likely to still be tabbing.
const FOCUSABLE_SELECTOR =
  '[href], button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])';

// Shared "which modal is on top" arbitration across every `useFocusTrap`
// instance. Modals in this app are normally mutually exclusive, but one
// reachable sequence stacks two: editing a note (dirty) -> Rename -> Choose
// location (opens FolderPickerModal) -> browser Back (useBlocker fires and
// mounts UnsavedChangesDialog on top). Without this, both traps steal Tab
// cycling independently and the later-activated one wins focus even though
// the earlier one is what's visually on top in some orderings -- keyboard
// input can land on a dialog the user can't see. Only the topmost active
// trap now steals initial focus and cycles Tab; callers also read the
// returned `isTopmost` to gate their own Escape handler the same way, so a
// single Escape press only ever cancels the modal actually in view.
let activeTraps: symbol[] = [];
const listeners = new Set<() => void>();

function notify() {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function topmost(): symbol | undefined {
  return activeTraps[activeTraps.length - 1];
}

/** Traps Tab/Shift+Tab focus cycling within `containerRef`'s own focusable
 * elements while `active` is true AND this instance is the topmost active
 * trap: focuses the container's first focusable element on activation,
 * wraps Tab at the ends so focus never reaches an element behind the
 * modal, and restores focus to whatever triggered the modal once it
 * deactivates or unmounts -- the standard modal keyboard-accessibility
 * contract (R5). Returns whether this instance is topmost, so the caller's
 * own Escape-key handler can stay coordinated with the same arbitration
 * (see the module-level comment above). Used by `ConfirmDialog`,
 * `FolderPickerModal`, and `UnsavedChangesDialog`. */
export function useFocusTrap(
  containerRef: RefObject<HTMLElement | null>,
  active: boolean,
): boolean {
  const [id] = useState(() => Symbol("focus-trap"));

  useEffect(() => {
    if (!active) return;
    activeTraps = [...activeTraps, id];
    notify();
    return () => {
      activeTraps = activeTraps.filter((trapId) => trapId !== id);
      notify();
    };
  }, [active, id]);

  const isTopmost = useSyncExternalStore(
    subscribe,
    () => topmost() === id,
    () => false,
  );

  useEffect(() => {
    if (!active || !isTopmost) return;

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
  }, [active, isTopmost, containerRef]);

  return isTopmost;
}

// A module-scoped flag for "the note editor has unsaved text", written by
// NoteViewPage and read by ReloadPrompt so a service-worker update can't
// reload the page out from under an unsaved buffer. A single shared value
// plus a listener set (same shape as the shared registry in
// hooks/useFocusTrap.ts) -- not a context, since only ReloadPrompt reads
// it, and not the only safeguard: NoteViewPage's own `beforeunload`
// handler is the hard data-loss backstop; this just lets the in-app toast
// defer instead of relying on the native "Leave site?" dialog.

let dirty = false;
const listeners = new Set<() => void>();

export function setEditorDirty(value: boolean): void {
  if (value === dirty) return;
  dirty = value;
  for (const listener of listeners) listener();
}

export function getEditorDirty(): boolean {
  return dirty;
}

export function subscribeEditorDirty(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

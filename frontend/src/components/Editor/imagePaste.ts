import type { Extension } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { errorMessage, uploadAttachment } from "../../api/client";

function findImageItem(
  items: DataTransferItemList | undefined,
): DataTransferItem | null {
  if (!items) return null;
  for (const item of items) {
    if (item.type.startsWith("image/")) return item;
  }
  return null;
}

// Replaces the placeholder's exact text wherever it currently sits in the
// document -- not at the position it was inserted at -- since the upload is
// async and the user may have kept typing (or deleted the placeholder
// entirely) before it resolves. Doing nothing when the placeholder is gone
// is deliberate: the user already removed it, so there is nothing left to
// mutate, and re-inserting text would surprise them.
function replacePlaceholder(
  view: EditorView,
  placeholder: string,
  replacement: string,
): void {
  const doc = view.state.doc.toString();
  const from = doc.indexOf(placeholder);
  if (from === -1) return;
  view.dispatch({
    changes: { from, to: from + placeholder.length, insert: replacement },
  });
}

/**
 * CodeMirror extension: pasting an image uploads it to the backend and
 * inserts markdown image syntax at the cursor. A placeholder is inserted
 * synchronously so the user sees immediate feedback, then swapped for the
 * real markdown (on success) or removed entirely (on failure, restoring the
 * note to its pre-paste content) once the upload settles. Non-image pastes
 * are left untouched -- returning `false` lets CodeMirror's default paste
 * handling proceed as if this extension weren't here.
 */
export function imagePasteExtension(
  notePath: string,
  onError: (msg: string | null) => void,
): Extension {
  return EditorView.domEventHandlers({
    paste(event, view) {
      const item = findImageItem(event.clipboardData?.items);
      if (!item) return false;

      event.preventDefault();
      const file = item.getAsFile();
      if (!file) return true;

      // Clear any error left over from a previous failed paste as soon as
      // this new attempt starts, not just on success -- otherwise a stale
      // error message would sit next to a placeholder that's actively
      // uploading, implying it already failed.
      onError(null);

      const id = crypto.randomUUID();
      const placeholder = `![Uploading...](uploading:${id})`;
      const pos = view.state.selection.main.head;
      view.dispatch({ changes: { from: pos, insert: placeholder } });

      uploadAttachment(notePath, file)
        .then((result) => {
          replacePlaceholder(view, placeholder, `![](${result.path})`);
        })
        .catch((err: unknown) => {
          replacePlaceholder(view, placeholder, "");
          onError(errorMessage(err));
        });

      return true;
    },
  });
}

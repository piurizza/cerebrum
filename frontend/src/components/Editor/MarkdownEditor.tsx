import { autocompletion } from "@codemirror/autocomplete";
import { markdown } from "@codemirror/lang-markdown";
import CodeMirror from "@uiw/react-codemirror";
import { useMemo, useState } from "react";
import { useNotes } from "../../context/NotesContext";
import { useTheme } from "../../context/ThemeContext";
import { imagePasteExtension } from "./imagePaste";
import { noteLinkCompletionSource } from "./noteLinkCompletion";

interface MarkdownEditorProps {
  value: string;
  onChange: (value: string) => void;
  currentPath: string;
  /** Freezes the editor in place (no keystrokes accepted) without
   * unmounting it or touching `value` -- used when a live offline
   * transition happens mid-edit (KTD6), so an in-progress unsaved draft
   * stays visible and copyable instead of being discarded or navigated
   * away from. Defaults to `false`. */
  readOnly?: boolean;
}

export function MarkdownEditor({
  value,
  onChange,
  currentPath,
  readOnly = false,
}: MarkdownEditorProps) {
  const { theme } = useTheme();
  const { notes } = useNotes();
  const [pasteError, setPasteError] = useState<string | null>(null);

  const extensions = useMemo(
    () => [
      markdown(),
      autocompletion({ override: [noteLinkCompletionSource(notes, currentPath)] }),
      // Omitted entirely when `readOnly` -- CodeMirror's `readOnly` facet
      // is opt-in per extension (consulted by commands that implement
      // editing, not enforced automatically), and this extension's own
      // `paste` domEventHandler never checked it. Left wired in, pasting an
      // image into a frozen offline draft (KTD6) still fired a real
      // `uploadAttachment()` POST and mutated the "preserved" draft via
      // placeholder insert/remove -- exactly what R3 says must not happen
      // while offline (review finding #2, 2026-08-31 code review).
      ...(readOnly ? [] : [imagePasteExtension(currentPath, setPasteError)]),
    ],
    [notes, currentPath, readOnly],
  );

  return (
    <>
      {pasteError && (
        <p className="error-text image-paste-error" role="alert">
          {pasteError}
        </p>
      )}
      <CodeMirror
        value={value}
        extensions={extensions}
        onChange={onChange}
        height="100%"
        theme={theme}
        readOnly={readOnly}
      />
    </>
  );
}

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
}

export function MarkdownEditor({ value, onChange, currentPath }: MarkdownEditorProps) {
  const { theme } = useTheme();
  const { notes } = useNotes();
  const [pasteError, setPasteError] = useState<string | null>(null);

  const extensions = useMemo(
    () => [
      markdown(),
      autocompletion({ override: [noteLinkCompletionSource(notes, currentPath)] }),
      imagePasteExtension(currentPath, setPasteError),
    ],
    [notes, currentPath],
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
      />
    </>
  );
}

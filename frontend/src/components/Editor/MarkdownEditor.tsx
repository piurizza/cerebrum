import { autocompletion } from "@codemirror/autocomplete";
import { markdown } from "@codemirror/lang-markdown";
import CodeMirror from "@uiw/react-codemirror";
import { useMemo } from "react";
import { useNotes } from "../../context/NotesContext";
import { usePrefersDark } from "../../hooks/usePrefersDark";
import { noteLinkCompletionSource } from "./noteLinkCompletion";

interface MarkdownEditorProps {
  value: string;
  onChange: (value: string) => void;
  currentPath: string;
}

export function MarkdownEditor({ value, onChange, currentPath }: MarkdownEditorProps) {
  const prefersDark = usePrefersDark();
  const { notes } = useNotes();

  const extensions = useMemo(
    () => [
      markdown(),
      autocompletion({ override: [noteLinkCompletionSource(notes, currentPath)] }),
    ],
    [notes, currentPath],
  );

  return (
    <CodeMirror
      value={value}
      extensions={extensions}
      onChange={onChange}
      height="100%"
      theme={prefersDark ? "dark" : "light"}
    />
  );
}

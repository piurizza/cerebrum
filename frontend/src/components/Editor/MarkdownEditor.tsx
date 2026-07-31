import { markdown } from "@codemirror/lang-markdown";
import CodeMirror from "@uiw/react-codemirror";
import { usePrefersDark } from "../../hooks/usePrefersDark";

interface MarkdownEditorProps {
  value: string;
  onChange: (value: string) => void;
}

export function MarkdownEditor({ value, onChange }: MarkdownEditorProps) {
  const prefersDark = usePrefersDark();

  return (
    <CodeMirror
      value={value}
      extensions={[markdown()]}
      onChange={onChange}
      height="100%"
      theme={prefersDark ? "dark" : "light"}
    />
  );
}

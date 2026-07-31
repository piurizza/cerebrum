import { markdown } from "@codemirror/lang-markdown";
import CodeMirror from "@uiw/react-codemirror";

interface MarkdownEditorProps {
  value: string;
  onChange: (value: string) => void;
}

export function MarkdownEditor({ value, onChange }: MarkdownEditorProps) {
  return (
    <CodeMirror
      value={value}
      extensions={[markdown()]}
      onChange={onChange}
      height="100%"
    />
  );
}

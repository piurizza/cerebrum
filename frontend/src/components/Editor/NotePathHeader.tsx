import { useState } from "react";

interface NotePathHeaderProps {
  path: string;
}

export function NotePathHeader({ path }: NotePathHeaderProps) {
  const [copied, setCopied] = useState(false);

  async function handleCopy() {
    await navigator.clipboard.writeText(path);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="note-path-header">
      <code className="note-path">{path}</code>
      <button type="button" className="btn btn-copy" onClick={handleCopy}>
        {copied ? "Copied!" : "Copy path"}
      </button>
    </div>
  );
}

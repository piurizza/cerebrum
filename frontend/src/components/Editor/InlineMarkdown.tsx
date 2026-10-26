import { type ReactNode, useMemo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import { REMARK_PLUGINS, useMarkdownComponents } from "./MarkdownPreview";

// What would make one line of text start a block rather than a paragraph:
// a heading, a quote, a list item (bulleted or numbered), a fenced code
// block or a link reference definition. A thematic break (`---`, `* * *`)
// is matched on its own below.
const BLOCK_START =
  /^(?:#|>|[-*+](?=[ \t]|$)|\d{1,9}(?=[.)](?:[ \t]|$))|`{3}|~{3}|\[[^\]]*\]:)/;
const THEMATIC_BREAK = /^([-*_])(?:[ \t]*\1){2,}[ \t]*$/;

/** `text` with a leading block marker backslash-escaped, so it renders as
 * the text of one paragraph: `1. Call the plumber` stays that text instead
 * of becoming a numbered list. Leading whitespace goes too, as four spaces
 * would start a code block. */
export function escapeBlockStart(text: string): string {
  const trimmed = text.trimStart();
  if (THEMATIC_BREAK.test(trimmed)) return `\\${trimmed}`;
  const marker = BLOCK_START.exec(trimmed);
  if (!marker) return trimmed;
  // A number is escaped at its `.` or `)`; anything else at its first
  // character.
  const at = /^\d/.test(trimmed) ? marker[0].length : 0;
  return `${trimmed.slice(0, at)}\\${trimmed.slice(at)}`;
}

function Unwrapped({ children }: { children?: ReactNode }) {
  return <>{children}</>;
}

interface InlineMarkdownProps {
  text: string;
  /** The note the text is from, which its links resolve against. */
  currentPath: string;
}

/** One line of markdown, such as a task's text, rendered inline the way
 * the note preview renders it: links and wikilinks resolve the same way,
 * emphasis and inline code show, raw HTML stays text. */
export function InlineMarkdown({ text, currentPath }: InlineMarkdownProps) {
  const base = useMarkdownComponents(currentPath);
  const components = useMemo<Components>(() => ({ ...base, p: Unwrapped }), [base]);
  return (
    <ReactMarkdown remarkPlugins={REMARK_PLUGINS} components={components}>
      {escapeBlockStart(text)}
    </ReactMarkdown>
  );
}

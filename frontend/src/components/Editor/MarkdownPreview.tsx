import ReactMarkdown, { type Components } from "react-markdown";
import { Link } from "react-router-dom";
import remarkGfm from "remark-gfm";
import { encodeNotePath } from "../../api/client";
import { resolveLinkTarget } from "../../lib/noteContent";

interface MarkdownPreviewProps {
  body: string;
  currentPath: string;
}

export function MarkdownPreview({ body, currentPath }: MarkdownPreviewProps) {
  const components: Components = {
    a({ href, children, ...props }) {
      const resolved = href ? resolveLinkTarget(currentPath, href) : null;
      if (resolved) {
        return <Link to={`/notes/${encodeNotePath(resolved)}`}>{children}</Link>;
      }
      return (
        <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
          {children}
        </a>
      );
    },
  };

  return (
    <div className="markdown-preview">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {body}
      </ReactMarkdown>
    </div>
  );
}

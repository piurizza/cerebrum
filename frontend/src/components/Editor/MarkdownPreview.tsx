import { useEffect, useState } from "react";
import ReactMarkdown, { type Components, type ExtraProps } from "react-markdown";
import { Link } from "react-router-dom";
import remarkGfm from "remark-gfm";
import { encodeNotePath, errorMessage, fetchAttachmentBlobUrl } from "../../api/client";
import { resolveAttachmentTarget, resolveLinkTarget } from "../../lib/noteContent";
import { MermaidDiagram } from "./MermaidDiagram";

interface MarkdownPreviewProps {
  body: string;
  currentPath: string;
}

interface AttachmentImageProps {
  attachmentPath: string;
  alt?: string;
}

// Renders an embedded image fetched through the app's authenticated request
// path rather than a bare `<img src="...">` (which can't carry an
// `Authorization` header, and a URL-embedded token would leak into browser
// history/logs). Needs its own component -- not just inline logic in the
// `img` override below -- because the fetch is async and needs local state
// to hold the resulting blob URL.
function AttachmentImage({ attachmentPath, alt }: AttachmentImageProps) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;

    setBlobUrl(null);
    setFailed(false);

    fetchAttachmentBlobUrl(attachmentPath)
      .then((url) => {
        if (cancelled) {
          // The component moved on to a different `attachmentPath` (or
          // unmounted) before this resolved -- revoke immediately instead
          // of leaking it, and don't set state after the fact.
          URL.revokeObjectURL(url);
          return;
        }
        objectUrl = url;
        setBlobUrl(url);
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          console.error(
            `Failed to load attachment ${attachmentPath}: ${errorMessage(err)}`,
          );
          setFailed(true);
        }
      });

    return () => {
      cancelled = true;
      if (objectUrl) {
        URL.revokeObjectURL(objectUrl);
      }
    };
  }, [attachmentPath]);

  if (failed) {
    return <span className="markdown-preview__image-error">Image unavailable</span>;
  }

  if (!blobUrl) {
    // Pending fetch -- render nothing rather than an `<img>` with an
    // empty/undefined `src`, which would show as a bare broken-image icon.
    return null;
  }

  return <img src={blobUrl} alt={alt} />;
}

type HastNode = NonNullable<ExtraProps["node"]>;
type HastChild = HastNode["children"][number];

function textContent(node: HastChild): string {
  if (node.type === "text") return node.value;
  if (node.type === "element") return node.children.map(textContent).join("");
  return "";
}

/** The source of a fenced ```mermaid block, or null for any other `<pre>`. */
function mermaidSource(pre: HastNode | undefined): string | null {
  const code = pre?.children[0];
  if (code?.type !== "element" || code.tagName !== "code") return null;
  const classes = code.properties.className;
  if (!Array.isArray(classes) || !classes.includes("language-mermaid")) return null;
  return textContent(code).replace(/\n$/, "");
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
    pre({ node, children, ...props }) {
      const source = mermaidSource(node);
      if (source !== null) {
        return <MermaidDiagram source={source} />;
      }
      return <pre {...props}>{children}</pre>;
    },
    img({ src, alt }) {
      const resolved =
        typeof src === "string" ? resolveAttachmentTarget(currentPath, src) : null;
      if (resolved) {
        return <AttachmentImage attachmentPath={resolved} alt={alt} />;
      }
      return <img src={src} alt={alt} />;
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

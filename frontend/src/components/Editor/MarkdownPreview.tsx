import { type ReactNode, useEffect, useMemo, useState } from "react";
import ReactMarkdown, { type Components, type ExtraProps } from "react-markdown";
import { Link } from "react-router-dom";
import remarkGfm from "remark-gfm";
import {
  encodeNotePath,
  errorMessage,
  fetchAttachmentBlobUrl,
  findAttachment,
} from "../../api/client";
import { useNotesIfLoaded } from "../../context/NotesContext";
import { resolveAttachmentTarget, resolveLinkTarget } from "../../lib/noteContent";
import {
  remarkWikilinks,
  WIKILINK_EMBED,
  WIKILINK_TARGET,
} from "../../lib/remarkWikilinks";
import { isAttachmentTarget, NoteLookup } from "../../lib/wikilinks";
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

interface WikilinkImageProps {
  name: string;
  fromNote: string;
  alt?: string;
}

// `![[cat.png]]` names an image, not a path: ask the server where it is,
// then show it like any other attachment.
function WikilinkImage({ name, fromNote, alt }: WikilinkImageProps) {
  const [path, setPath] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setPath(null);
    setMissing(false);
    findAttachment(name, fromNote)
      .then((found) => {
        if (!cancelled) setPath(found.path);
      })
      .catch(() => {
        if (!cancelled) setMissing(true);
      });
    return () => {
      cancelled = true;
    };
  }, [name, fromNote]);

  if (missing) return <Unresolved>{name}</Unresolved>;
  if (!path) return null;
  return <AttachmentImage attachmentPath={path} alt={alt} />;
}

function Unresolved({ children }: { children: ReactNode }) {
  return (
    <span
      className="markdown-preview__unresolved"
      title="Nothing in the vault has this name"
    >
      {children}
    </span>
  );
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
  const notes = useNotesIfLoaded();
  const lookup = useMemo(() => new NoteLookup(notes.map((note) => note.path)), [notes]);

  const components: Components = {
    a({ href, children, node, ...props }) {
      const wikilinkTarget = node?.properties[WIKILINK_TARGET];
      if (typeof wikilinkTarget === "string") {
        const note = isAttachmentTarget(wikilinkTarget)
          ? null
          : lookup.resolve(currentPath, wikilinkTarget);
        if (!note) return <Unresolved>{children}</Unresolved>;
        return <Link to={`/notes/${encodeNotePath(note)}`}>{children}</Link>;
      }
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
    img({ src, alt, node }) {
      const embed = node?.properties[WIKILINK_EMBED];
      if (typeof embed === "string") {
        return <WikilinkImage name={embed} fromNote={currentPath} alt={alt} />;
      }
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
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkWikilinks]}
        components={components}
      >
        {body}
      </ReactMarkdown>
    </div>
  );
}

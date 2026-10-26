import {
  type ComponentProps,
  createContext,
  type ReactNode,
  useContext,
  useEffect,
  useId,
  useMemo,
  useState,
} from "react";
import ReactMarkdown, { type Components, type ExtraProps } from "react-markdown";
import { Link } from "react-router-dom";
import remarkGfm from "remark-gfm";
import {
  encodeNotePath,
  errorMessage,
  fetchAttachmentBlobUrl,
  findAttachment,
} from "../../api/client";
import { useNoteLookup } from "../../context/NotesContext";
import { resolveAttachmentTarget, resolveLinkTarget } from "../../lib/noteContent";
import {
  remarkWikilinks,
  WIKILINK_EMBED,
  WIKILINK_TARGET,
} from "../../lib/remarkWikilinks";
import { hasTaskLine, splitLines, taskInLines } from "../../lib/tasks";
import { isAttachmentTarget } from "../../lib/wikilinks";
import { MermaidDiagram } from "./MermaidDiagram";

/** What a preview needs to tick and untick its tasks. */
export interface TaskToggle {
  /** The note's raw content `body` was cut from: an item's checkbox works
   * only when its file line there still holds a task. */
  content: string;
  disabled: boolean;
  /** Why the checkboxes are disabled, shown above the note when it has
   * tasks; null for none. */
  hint: string | null;
  onToggle: (task: { line: number; text: string; done: boolean }) => void;
}

interface MarkdownPreviewProps {
  body: string;
  currentPath: string;
  /** How many lines of the file come before `body` (its frontmatter), so
   * that a rendered task knows its file line. */
  lineOffset?: number;
  /** Without it, task checkboxes show their state but can't be ticked. */
  tasks?: TaskToggle;
  /** The file line of a task item to highlight. */
  highlightLine?: number | null;
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

// Task text and the preview render markdown the same way: these plugins
// and the components below, with react-markdown's defaults (no raw HTML,
// unsafe URL schemes dropped).
export const REMARK_PLUGINS = [remarkGfm, remarkWikilinks];

/** How rendered markdown shows links, wikilinks, images and diagrams for
 * the note at `currentPath`: shared by the note preview and the task text
 * (`InlineMarkdown`), so a link resolves the same way in both. */
export function useMarkdownComponents(currentPath: string): Components {
  const lookup = useNoteLookup();

  // Memoized so that a re-render (a tick adopting the new content, say)
  // updates the elements in place instead of remounting them, which would
  // drop the keyboard focus from the checkbox just ticked.
  return useMemo(
    () => ({
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
    }),
    [lookup, currentPath],
  );
}

interface TaskItemsState {
  lineOffset: number;
  tasks: TaskToggle | undefined;
  /** `tasks.content` split into lines once, rather than by each checkbox. */
  taskLines: readonly string[] | undefined;
  hintId: string | undefined;
  highlightLine: number | null;
}

// Per render, passed down by context rather than baked into the components,
// which stay the same across renders (see useMarkdownComponents).
const TaskItemsContext = createContext<TaskItemsState>({
  lineOffset: 0,
  tasks: undefined,
  taskLines: undefined,
  hintId: undefined,
  highlightLine: null,
});

// The task item a checkbox belongs to: its file line and its own text.
const TaskItemContext = createContext<{ line: number; label: string } | null>(null);

/** An item's own text, without its checkbox or the lists nested in it. */
function itemLabel(item: HastNode): string {
  return item.children
    .filter(
      (child) =>
        child.type !== "element" || !["ul", "ol", "input"].includes(child.tagName),
    )
    .map(textContent)
    .join("")
    .replace(/\s+/g, " ")
    .trim();
}

function TaskListItem({
  node,
  className,
  children,
  ...props
}: ComponentProps<"li"> & ExtraProps) {
  const { lineOffset, highlightLine } = useContext(TaskItemsContext);
  const start = node?.position?.start.line;
  if (
    !node ||
    start === undefined ||
    !className?.split(" ").includes("task-list-item")
  ) {
    return (
      <li className={className} {...props}>
        {children}
      </li>
    );
  }
  const line = start + lineOffset;
  const highlighted = line === highlightLine;
  return (
    <TaskItemContext.Provider value={{ line, label: itemLabel(node) }}>
      <li
        className={highlighted ? `${className} task-list-item--highlight` : className}
        data-source-line={line}
        {...props}
      >
        {highlighted && <span className="visually-hidden">The task you opened: </span>}
        {children}
      </li>
    </TaskItemContext.Provider>
  );
}

// GFM renders a task's checkbox as a disabled input. Here it is the real,
// named checkbox, live only when its file line holds that task, so a tick
// never lands on the wrong line.
function TaskCheckbox({
  node: _node,
  type,
  checked,
  ...props
}: ComponentProps<"input"> & ExtraProps) {
  const item = useContext(TaskItemContext);
  const { tasks, taskLines, hintId } = useContext(TaskItemsContext);
  if (type !== "checkbox" || item === null) {
    return <input type={type} checked={checked} {...props} />;
  }
  const task = taskLines ? taskInLines(taskLines, item.line) : null;
  const live = tasks !== undefined && !tasks.disabled && task !== null;
  return (
    <input
      type="checkbox"
      className="task-checkbox"
      checked={Boolean(checked)}
      disabled={!live}
      aria-label={item.label}
      aria-describedby={hintId}
      onChange={() => {
        if (live)
          tasks.onToggle({ line: item.line, text: task.text, done: !task.checked });
      }}
    />
  );
}

export function MarkdownPreview({
  body,
  currentPath,
  lineOffset = 0,
  tasks,
  highlightLine = null,
}: MarkdownPreviewProps) {
  const base = useMarkdownComponents(currentPath);
  const components = useMemo<Components>(
    () => ({ ...base, li: TaskListItem, input: TaskCheckbox }),
    [base],
  );
  const hintId = useId();
  const hint = tasks?.hint;
  const showHint = useMemo(() => Boolean(hint) && hasTaskLine(body), [hint, body]);
  const content = tasks?.content;
  const taskLines = useMemo(
    () => (content === undefined ? undefined : splitLines(content)),
    [content],
  );
  const state = useMemo<TaskItemsState>(
    () => ({
      lineOffset,
      tasks,
      taskLines,
      hintId: showHint ? hintId : undefined,
      highlightLine,
    }),
    [lineOffset, tasks, taskLines, showHint, hintId, highlightLine],
  );

  return (
    <div className="markdown-preview">
      {showHint && (
        <p id={hintId} className="markdown-preview__task-hint">
          {tasks?.hint}
        </p>
      )}
      <TaskItemsContext.Provider value={state}>
        <ReactMarkdown remarkPlugins={REMARK_PLUGINS} components={components}>
          {body}
        </ReactMarkdown>
      </TaskItemsContext.Provider>
    </div>
  );
}

import { useId } from "react";
import { Link } from "react-router-dom";
import { encodeNotePath } from "../../api/client";
import type { TaskItem } from "../../types/note";
import { InlineMarkdown } from "../Editor/InlineMarkdown";

const doneDateFormatter = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });

/** A done date (YYYY-MM-DD) as a local calendar day, e.g. "Oct 26, 2026".
 * Built from its parts: `new Date("2026-10-26")` is midnight UTC, which
 * is the day before west of Greenwich. */
export function formatDoneDate(isoDay: string): string {
  const [year, month, day] = isoDay.split("-").map(Number);
  return doneDateFormatter.format(new Date(year, month - 1, day));
}

interface TaskRowProps {
  /** The task as the row shows it: `done` is the checkbox's state. */
  task: TaskItem;
  /** "hidden" on a read-only vault, "disabled" offline. */
  toggle: "enabled" | "disabled" | "hidden";
  onToggle: () => void;
  /** Given while the row's tick or untick can still be taken back. */
  onUndo?: () => void;
  /** Shown although the filters would hide it (a task just added). */
  outsideFilters?: boolean;
  /** Names the note, for a list not grouped by note. */
  showNote?: boolean;
}

/** One task on the Tasks page: its checkbox, its text as inline markdown,
 * its done date and a link to it in its note. The checkbox sits apart
 * from the text, so a tap on a link in the text never ticks the task. */
export function TaskRow({
  task,
  toggle,
  onToggle,
  onUndo,
  outsideFilters = false,
  showNote = false,
}: TaskRowProps) {
  const textId = useId();
  const classes = ["task-row"];
  // Struck through while a tick can still be taken back; a task long done
  // on the Done tab just shows as ticked.
  if (onUndo) classes.push(task.done ? "is-pending is-struck" : "is-pending");
  if (outsideFilters) classes.push("is-outside");

  return (
    <li className={classes.join(" ")}>
      {toggle !== "hidden" && (
        // The label only widens the checkbox's hit area; its name is the
        // task text, read from the text beside it.
        <label className="task-row-check">
          <input
            type="checkbox"
            className="task-checkbox"
            checked={task.done}
            disabled={toggle === "disabled"}
            aria-labelledby={textId}
            onChange={onToggle}
          />
        </label>
      )}
      <div className="task-row-body">
        <span id={textId} className="task-row-text">
          <InlineMarkdown text={task.text} currentPath={task.path} />
        </span>
        <span className="task-row-meta">
          {task.done && task.done_date && (
            <time className="task-row-date" dateTime={task.done_date}>
              {formatDoneDate(task.done_date)}
            </time>
          )}
          {showNote && <span className="task-row-note">{task.title}</span>}
          {outsideFilters && (
            <span className="task-row-flag">Outside the current filters</span>
          )}
          <Link
            className="task-row-open"
            to={`/notes/${encodeNotePath(task.path)}?line=${task.line}`}
            aria-describedby={textId}
          >
            Open
          </Link>
          {onUndo && (
            <button
              type="button"
              className="btn btn-sm task-row-undo"
              aria-describedby={textId}
              onClick={onUndo}
            >
              Undo
            </button>
          )}
        </span>
      </div>
    </li>
  );
}

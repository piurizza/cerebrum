import {
  type KeyboardEvent,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { Link } from "react-router-dom";
import {
  addTask,
  encodeNotePath,
  errorMessage,
  getDoneTasks,
  getTasks,
  setTaskDone,
} from "../api/client";
import { TagChip } from "../components/TagChip";
import { TaskAddBox } from "../components/Tasks/TaskAddBox";
import { TaskFilters } from "../components/Tasks/TaskFilters";
import { TaskRow } from "../components/Tasks/TaskRow";
import { useRefreshNotesIfLoaded } from "../context/NotesContext";
import { useTagSelection } from "../context/TagSelectionContext";
import { useCanWrite, useVaultReadOnly } from "../hooks/useCanWrite";
import { getDailyNoteHeading, localDateFromIso, localIsoDate } from "../lib/dailyNote";
import { findDuplicateTitles } from "../lib/duplicateTitles";
import { normalizeTag } from "../lib/tagQuery";
import {
  byDoneDateDesc,
  byPathAndLine,
  DONE_LIST_DAYS,
  describeTaskFilters,
  doneListSince,
  hasActiveFilters,
  type TaskFilterState,
  taskFilter,
  taskFolders,
  taskKey,
} from "../lib/taskList";
import { isTaskChangedError, TASK_CHANGED_MESSAGE } from "../lib/tasks";
import type { TaskItem } from "../types/note";

type Tab = "open" | "done";

/** How long a ticked or unticked row stays in its list, with Undo. */
const UNDO_MS = 5000;

const TABS: { id: Tab; label: string }[] = [
  { id: "open", label: "Open" },
  { id: "done", label: "Done" },
];

const dayHeadingFormatter = new Intl.DateTimeFormat(undefined, { dateStyle: "full" });

/** A tick or untick still in its Undo window. The row stays in the list
 * it was changed in, showing its new state, until the window ends. */
interface PendingToggle {
  origin: Tab;
  /** The task as it was before. */
  before: TaskItem;
  /** The task as the row shows it now. */
  shown: TaskItem;
  /** Set once Undo is pressed: the write's own outcome no longer counts. */
  token: { undone: boolean };
  /** Settles with the task as written, or null when nothing was written. */
  write: Promise<TaskItem | null>;
}

interface NoteGroup {
  path: string;
  title: string;
  tasks: TaskItem[];
}

interface DayGroup {
  day: string;
  tasks: TaskItem[];
}

function withoutKey(keys: ReadonlySet<string>, key: string): ReadonlySet<string> {
  if (!keys.has(key)) return keys;
  const next = new Set(keys);
  next.delete(key);
  return next;
}

function failedWriteMessage(err: unknown, done: boolean): string {
  if (isTaskChangedError(err)) return TASK_CHANGED_MESSAGE;
  return `The task wasn't ${done ? "ticked" : "unticked"}: ${errorMessage(err)}`;
}

// Partitions an ordered list into per-note buckets -- it doesn't re-sort.
// Map insertion order keeps the list's order both across groups and
// within each group's own task list.
function groupByNote(tasks: readonly TaskItem[]): NoteGroup[] {
  const byPath = new Map<string, NoteGroup>();
  for (const task of tasks) {
    let group = byPath.get(task.path);
    if (!group) {
      group = { path: task.path, title: task.title, tasks: [] };
      byPath.set(task.path, group);
    }
    group.tasks.push(task);
  }
  return [...byPath.values()];
}

function groupByDay(tasks: readonly TaskItem[]): DayGroup[] {
  const byDay = new Map<string, DayGroup>();
  for (const task of tasks) {
    const day = task.done_date ?? "";
    let group = byDay.get(day);
    if (!group) {
      group = { day, tasks: [] };
      byDay.set(day, group);
    }
    group.tasks.push(task);
  }
  return [...byDay.values()];
}

function dayHeading(isoDay: string, now: Date): string {
  if (isoDay === localIsoDate(now)) return "Today";
  const yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
  if (isoDay === localIsoDate(yesterday)) return "Yesterday";
  return dayHeadingFormatter.format(localDateFromIso(isoDay));
}

/** The working task list: add a task to today's daily note, tick and
 * untick tasks, and narrow both the open list and the last 14 days of done
 * tasks by the shared tag selection, a folder and words. */
export function TasksPage() {
  const [openTasks, setOpenTasks] = useState<TaskItem[] | null>(null);
  const [doneTasks, setDoneTasks] = useState<TaskItem[] | null>(null);
  const [openError, setOpenError] = useState<string | null>(null);
  const [doneError, setDoneError] = useState<string | null>(null);
  // Tasks added during this visit, by key: listed even when the filters
  // would hide them. Whether one is listed at all is the open list's call.
  const [addedKeys, setAddedKeys] = useState<ReadonlySet<string>>(new Set());
  const [tab, setTab] = useState<Tab>("open");
  const [folder, setFolder] = useState("");
  const [words, setWords] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const { chips, removeChip, clearChips } = useTagSelection();
  const canWrite = useCanWrite();
  const vaultReadOnly = useVaultReadOnly();
  const refreshNotes = useRefreshNotesIfLoaded();
  const tabsId = useId();
  const tabRefs = useRef<Record<Tab, HTMLButtonElement | null>>({
    open: null,
    done: null,
  });

  // The ref is what the write callbacks read, the state what renders.
  const pendingRef = useRef(new Map<string, PendingToggle>());
  const [pending, setPending] = useState<ReadonlyMap<string, PendingToggle>>(
    pendingRef.current,
  );
  const timers = useRef(new Map<string, number>());

  const changePending = useCallback(
    (change: (map: Map<string, PendingToggle>) => void) => {
      const next = new Map(pendingRef.current);
      change(next);
      pendingRef.current = next;
      setPending(next);
    },
    [],
  );

  const dropPending = useCallback(
    (key: string) => {
      window.clearTimeout(timers.current.get(key));
      timers.current.delete(key);
      changePending((map) => map.delete(key));
    },
    [changePending],
  );

  useEffect(() => {
    const running = timers.current;
    return () => {
      for (const timer of running.values()) window.clearTimeout(timer);
    };
  }, []);

  // A list fetched before the latest write settled may predate it, and
  // an older response landing after a newer one would roll the list back:
  // either is dropped, as the fetch that follows is fresher.
  const lastIssued = useRef(0);
  const lastApplied = useRef(0);
  const writesSettled = useRef(0);
  const loaded = useRef({ open: false, done: false });

  const refresh = useCallback(async () => {
    lastIssued.current += 1;
    const request = lastIssued.current;
    const writesAtIssue = writesSettled.current;
    const [open, done] = await Promise.allSettled([
      getTasks(),
      getDoneTasks(doneListSince()),
    ]);
    if (request < lastApplied.current || writesAtIssue !== writesSettled.current)
      return;
    lastApplied.current = request;
    // A refetch that fails keeps the last good list, as the sidebar does:
    // only a list never loaded shows the error.
    if (open.status === "fulfilled") {
      loaded.current.open = true;
      setOpenTasks(open.value);
      setOpenError(null);
      // An added task the server no longer lists as open (ticked or
      // deleted elsewhere) is gone, unless its own tick is still in its
      // Undo window.
      const listed = new Set(open.value.map(taskKey));
      setAddedKeys((keys) => {
        const kept = [...keys].filter(
          (key) => listed.has(key) || pendingRef.current.has(key),
        );
        return kept.length === keys.size ? keys : new Set(kept);
      });
    } else if (!loaded.current.open) {
      setOpenError(errorMessage(open.reason));
    }
    if (done.status === "fulfilled") {
      loaded.current.done = true;
      setDoneTasks(done.value);
      setDoneError(null);
    } else if (!loaded.current.done) {
      setDoneError(errorMessage(done.reason));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Ticks made in the note, on another device or by an assistant only
  // reach the list through a fresh fetch, so one is made whenever the
  // window comes back to the foreground. Coming back to the tab fires both
  // events, so one fetch serves the pair; a write's refetch never waits on
  // it and always fetches anew.
  useEffect(() => {
    let inFlight = false;

    function refreshWhenVisible() {
      if (inFlight || document.visibilityState !== "visible") return;
      inFlight = true;
      void refresh().finally(() => {
        inFlight = false;
      });
    }
    window.addEventListener("focus", refreshWhenVisible);
    document.addEventListener("visibilitychange", refreshWhenVisible);
    return () => {
      window.removeEventListener("focus", refreshWhenVisible);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [refresh]);

  // A task as the server wrote it moves to the list it now belongs in at
  // once, without waiting for the refetch.
  const applyWritten = useCallback((task: TaskItem) => {
    const key = taskKey(task);
    const without = (list: TaskItem[]) => list.filter((item) => taskKey(item) !== key);
    setOpenTasks(
      (list) => list && (task.done ? without(list) : [...without(list), task]),
    );
    setDoneTasks(
      (list) => list && (task.done ? [...without(list), task] : without(list)),
    );
  }, []);

  const writeSettled = useCallback(() => {
    writesSettled.current += 1;
    void refresh();
  }, [refresh]);

  const undo = useCallback(
    async (key: string) => {
      const entry = pendingRef.current.get(key);
      if (!entry) return;
      entry.token.undone = true;
      dropPending(key);
      setNotice(null);
      const { before } = entry;
      applyWritten(before);
      // Nothing to take back when the write itself failed.
      if ((await entry.write) === null) return;
      try {
        const { task } = await setTaskDone({
          path: before.path,
          line: before.line,
          text: before.text,
          done: before.done,
          // An untick taken back keeps the day the task was done.
          date: before.done ? before.done_date : null,
        });
        applyWritten(task);
      } catch (err) {
        setNotice(failedWriteMessage(err, before.done));
      } finally {
        writeSettled();
      }
    },
    [applyWritten, dropPending, writeSettled],
  );

  const toggle = useCallback(
    (task: TaskItem, origin: Tab) => {
      const key = taskKey(task);
      // A row still in its Undo window takes its checkbox as Undo.
      if (pendingRef.current.has(key)) {
        void undo(key);
        return;
      }
      if (!canWrite) return;
      setNotice(null);
      const done = !task.done;
      const date = done ? localIsoDate() : null;
      const token = { undone: false };
      const write = setTaskDone({
        path: task.path,
        line: task.line,
        text: task.text,
        done,
        date,
      })
        .then(({ task: written }) => {
          if (!token.undone) applyWritten(written);
          return written;
        })
        .catch((err: unknown) => {
          if (!token.undone) {
            if (pendingRef.current.get(key)?.token === token) dropPending(key);
            setNotice(failedWriteMessage(err, done));
          }
          return null;
        })
        .finally(writeSettled);
      const entry: PendingToggle = {
        origin,
        before: task,
        // An unticked row keeps its done date while it stays in the done
        // list, so it stays under its day.
        shown: { ...task, done, done_date: done ? date : task.done_date },
        token,
        write,
      };
      changePending((map) => map.set(key, entry));
      timers.current.set(
        key,
        window.setTimeout(() => {
          if (pendingRef.current.get(key)?.token !== token) return;
          dropPending(key);
          // A task added here and then ticked has nothing left to show.
          if (done) setAddedKeys((keys) => withoutKey(keys, key));
        }, UNDO_MS),
      );
    },
    [canWrite, undo, applyWritten, dropPending, writeSettled, changePending],
  );

  const handleAdd = useCallback(
    async (text: string) => {
      const now = new Date();
      const { task } = await addTask({
        text,
        date: localIsoDate(now),
        heading: getDailyNoteHeading(now),
      });
      // In the open list at once; a fetch sent before the add is dropped,
      // so the next list applied is one the server made after it.
      setAddedKeys((keys) => new Set(keys).add(taskKey(task)));
      applyWritten(task);
      setTab("open");
      writeSettled();
      // The task may have created today's note.
      void refreshNotes();
    },
    [applyWritten, writeSettled, refreshNotes],
  );

  const filters = useMemo<TaskFilterState>(
    () => ({ chips, folder, words }),
    [chips, folder, words],
  );
  const filtering = hasActiveFilters(filters);
  const matchesFilters = useMemo(() => taskFilter(filters), [filters]);

  // The lists as fetched, with the rows still in their Undo window kept
  // in the list they were changed in.
  const openRows = useMemo(() => {
    if (openTasks === null) return null;
    const rows = new Map(openTasks.map((task) => [taskKey(task), task]));
    for (const [key, entry] of pending) {
      if (entry.origin === "open") rows.set(key, entry.shown);
    }
    return [...rows.values()].sort(byPathAndLine);
  }, [openTasks, pending]);

  const doneRows = useMemo(() => {
    if (doneTasks === null) return null;
    const rows = new Map(doneTasks.map((task) => [taskKey(task), task]));
    for (const [key, entry] of pending) {
      if (entry.origin === "done") rows.set(key, entry.shown);
    }
    return [...rows.values()].sort(byDoneDateDesc);
  }, [doneTasks, pending]);

  // A task added here is shown even when the filters would hide it.
  const visibleOpen = useMemo(
    () =>
      (openRows ?? []).filter(
        (task) => addedKeys.has(taskKey(task)) || matchesFilters(task),
      ),
    [openRows, addedKeys, matchesFilters],
  );
  const visibleDone = useMemo(
    () => (doneRows ?? []).filter(matchesFilters),
    [doneRows, matchesFilters],
  );

  const folders = useMemo(
    () => taskFolders([...(openRows ?? []), ...(doneRows ?? [])]),
    [openRows, doneRows],
  );
  const noteGroups = useMemo(() => groupByNote(visibleOpen), [visibleOpen]);
  const dayGroups = useMemo(() => groupByDay(visibleDone), [visibleDone]);
  // Only show the disambiguating path for titles that actually collide,
  // so the common case (unique titles) stays uncluttered.
  const duplicateTitles = useMemo(
    () => findDuplicateTitles(noteGroups, (group) => group.title),
    [noteGroups],
  );

  const toggleMode = vaultReadOnly ? "hidden" : canWrite ? "enabled" : "disabled";

  function clearFilters() {
    clearChips();
    setFolder("");
    setWords("");
  }

  function handleTabKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const index = TABS.findIndex((item) => item.id === tab);
    let next: (typeof TABS)[number];
    switch (event.key) {
      case "ArrowRight":
        next = TABS[(index + 1) % TABS.length];
        break;
      case "ArrowLeft":
        next = TABS[(index - 1 + TABS.length) % TABS.length];
        break;
      case "Home":
        next = TABS[0];
        break;
      case "End":
        next = TABS[TABS.length - 1];
        break;
      default:
        return;
    }
    event.preventDefault();
    setTab(next.id);
    tabRefs.current[next.id]?.focus();
  }

  function renderRow(task: TaskItem, origin: Tab) {
    const key = taskKey(task);
    const entry = pending.get(key);
    return (
      <TaskRow
        key={key}
        task={task}
        toggle={toggleMode}
        onToggle={() => toggle(task, origin)}
        onUndo={entry?.origin === origin ? () => void undo(key) : undefined}
        outsideFilters={
          origin === "open" && filtering && addedKeys.has(key) && !matchesFilters(task)
        }
        showNote={origin === "done"}
      />
    );
  }

  function emptyFiltered(what: string) {
    return (
      <div className="task-empty">
        <p className="empty-hint">
          {what} match {describeTaskFilters(filters)}.
        </p>
        <button type="button" className="btn btn-sm" onClick={clearFilters}>
          Clear filters
        </button>
      </div>
    );
  }

  function openPanel() {
    if (openError) {
      return (
        <p className="error-text" role="alert">
          Failed to load tasks: {openError}
        </p>
      );
    }
    if (openRows === null) return <p className="loading-indicator">Loading...</p>;
    if (openRows.length === 0)
      return <p className="empty-hint">No open tasks in the vault.</p>;
    if (visibleOpen.length === 0) return emptyFiltered("No open tasks");
    return noteGroups.map((group) => (
      <section key={group.path} className="task-group">
        <h2 className="task-group-title">
          <Link to={`/notes/${encodeNotePath(group.path)}`}>{group.title}</Link>
          {duplicateTitles.has(group.title) && (
            <span className="task-group-path"> ({group.path})</span>
          )}
        </h2>
        <ul className="task-list">
          {group.tasks.map((task) => renderRow(task, "open"))}
        </ul>
      </section>
    ));
  }

  function donePanel() {
    if (doneError) {
      return (
        <p className="error-text" role="alert">
          Failed to load done tasks: {doneError}
        </p>
      );
    }
    if (doneRows === null) return <p className="loading-indicator">Loading...</p>;
    if (doneRows.length === 0) {
      return (
        <p className="empty-hint">Nothing ticked in the last {DONE_LIST_DAYS} days.</p>
      );
    }
    if (visibleDone.length === 0) {
      return emptyFiltered(`No tasks ticked in the last ${DONE_LIST_DAYS} days`);
    }
    const now = new Date();
    return dayGroups.map((group) => (
      <section key={group.day} className="task-group">
        <h2 className="task-group-title">{dayHeading(group.day, now)}</h2>
        <ul className="task-list">
          {group.tasks.map((task) => renderRow(task, "done"))}
        </ul>
      </section>
    ));
  }

  return (
    <div className="tasks-page">
      <h1>Tasks</h1>
      {!vaultReadOnly && <TaskAddBox onAdd={handleAdd} disabled={!canWrite} />}
      {chips.length > 0 && (
        <div className="tag-selected task-chips">
          {chips.map((chip) => (
            <TagChip
              key={normalizeTag(chip.tag)}
              chip={chip}
              onRemove={() => removeChip(chip.tag)}
            />
          ))}
          <button type="button" className="btn btn-sm" onClick={clearChips}>
            Clear
          </button>
        </div>
      )}
      <TaskFilters
        folders={folders}
        folder={folder}
        words={words}
        onFolderChange={setFolder}
        onWordsChange={setWords}
      />
      <div className="task-tabs" role="tablist" aria-label="Task lists">
        {TABS.map((item) => (
          <button
            key={item.id}
            ref={(element) => {
              tabRefs.current[item.id] = element;
            }}
            type="button"
            role="tab"
            id={`${tabsId}-${item.id}`}
            className={item.id === tab ? "task-tab is-active" : "task-tab"}
            aria-selected={item.id === tab}
            aria-controls={`${tabsId}-panel`}
            tabIndex={item.id === tab ? 0 : -1}
            onClick={() => setTab(item.id)}
            onKeyDown={handleTabKeyDown}
          >
            {item.label}
          </button>
        ))}
      </div>
      {notice && (
        <p className="error-text task-notice" role="alert">
          {notice}
        </p>
      )}
      <div
        className="task-panel"
        role="tabpanel"
        id={`${tabsId}-panel`}
        aria-labelledby={`${tabsId}-${tab}`}
      >
        {tab === "open" ? openPanel() : donePanel()}
      </div>
    </div>
  );
}

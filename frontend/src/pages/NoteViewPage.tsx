import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useBlocker, useNavigate, useParams, useSearchParams } from "react-router-dom";
import {
  ApiError,
  CachedNoteError,
  encodeNotePath,
  errorMessage,
  getLiveNote,
  getNote,
  NoteConflictError,
  putNote,
  setTaskDone,
} from "../api/client";
import { BacklinksPanel } from "../components/Backlinks/BacklinksPanel";
import { UnsavedChangesDialog } from "../components/ConfirmDialog/UnsavedChangesDialog";
import { MarkdownEditor } from "../components/Editor/MarkdownEditor";
import { MarkdownPreview, type TaskToggle } from "../components/Editor/MarkdownPreview";
import { NotePathHeader } from "../components/Editor/NotePathHeader";
import {
  SaveConflictDialog,
  UnsavedTextPanel,
} from "../components/Editor/SaveConflictDialog";
import { useOffline } from "../context/OfflineContext";
import { useTheme } from "../context/ThemeContext";
import { useZenMode } from "../context/ZenModeContext";
import { useCanWrite, useVaultReadOnly } from "../hooks/useCanWrite";
import { localIsoDate } from "../lib/dailyNote";
import { setEditorDirty } from "../lib/editorDirty";
import { mergeNote } from "../lib/mergeNote";
import { frontmatterLineCount, stripFrontmatter } from "../lib/noteContent";
import { isTaskChangedError, TASK_CHANGED_MESSAGE, taskOnLine } from "../lib/tasks";
import type { Note } from "../types/note";

type ViewMode = "edit" | "preview";

// "conflict" means the save was refused and the conflict dialog is open.
type SaveOutcome = "saved" | "conflict";

// The merge needs the file as it is now, and only a cached copy came back.
const OFFLINE_SAVE_MESSAGE = "Offline -- your changes aren't saved yet.";

function saveErrorMessage(err: unknown): string {
  return err instanceof CachedNoteError ? OFFLINE_SAVE_MESSAGE : errorMessage(err);
}

// A tick writes the file, so it would be refused against unsaved edits or,
// worse, leave them out of date: the buffer must be saved first.
const SAVE_FIRST_HINT = "Save first to tick tasks here.";

const TASK_MOVED_MESSAGE =
  "This task has moved since the list was loaded, so the note opens at the top.";

// How long a task opened from the list stays highlighted.
const HIGHLIGHT_MS = 2000;

/** The `?line=N` a task opens its note at, or null. */
function openLine(value: string | null): number | null {
  return value !== null && /^[1-9]\d*$/.test(value) ? Number(value) : null;
}

// Best-effort platform detection for the shortcut hint (R6) --
// `navigator.platform` is deprecated but still universally supported;
// worst case a non-Mac user briefly sees "⌘" instead of "Ctrl", which is
// cosmetic only, since the keydown handler above already accepts both.
const isMac =
  typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

export function NoteViewPage() {
  const params = useParams();
  const path = params["*"] ?? "";
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const lineToOpen = openLine(searchParams.get("line"));
  const [content, setContent] = useState("");
  // The note as last loaded or saved, and its version: the base of the
  // three-way merge when a save is refused because the file changed
  // elsewhere (KTD5). No version (a response cached before notes had one)
  // saves unconditionally, as before.
  const [savedContent, setSavedContent] = useState("");
  const [baseVersion, setBaseVersion] = useState<string | undefined>(undefined);
  const [title, setTitle] = useState("");
  const [created, setCreated] = useState<string | null>(null);
  const [updated, setUpdated] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [mode, setMode] = useState<ViewMode>("preview");
  const [blockerError, setBlockerError] = useState<string | null>(null);
  // Inline and persistent, not a toast: a refused save (a 403 from a
  // read-only vault, say) must stay visible until the next attempt.
  const [saveError, setSaveError] = useState<string | null>(null);
  // Holds the raw fetch failure, not a pre-formatted message -- whether to
  // show the offline-specific copy or the raw error text is decided at
  // render time from the *current* `isOffline`, not baked in when the
  // catch fires. That also keeps `isOffline` out of this effect's own
  // dependency list below, which matters: this effect should only re-run
  // when `path` changes (a new note being opened), not every time
  // connectivity flips mid-fetch -- refetching on every online/offline
  // toggle would fight the in-flight request.
  const [loadError, setLoadError] = useState<unknown>(null);
  const [conflictOpen, setConflictOpen] = useState(false);
  // The refused save found the note deleted, not changed.
  const [conflictDeleted, setConflictDeleted] = useState(false);
  const [conflictError, setConflictError] = useState<string | null>(null);
  // The edits a Reload took out of the editor, kept on screen to copy
  // until dismissed.
  const [unsavedText, setUnsavedText] = useState<string | null>(null);
  // A preview tick's outcome: the shared "this task changed" message (or
  // the open-at-line "moved" one), and any other failure.
  const [taskNotice, setTaskNotice] = useState<string | null>(null);
  const [taskError, setTaskError] = useState<string | null>(null);
  const [highlightLine, setHighlightLine] = useState<number | null>(null);
  // A ref, not state: a second click before the first tick re-renders must
  // already see it. The checkboxes aren't disabled meanwhile, which would
  // take the keyboard focus off the one just ticked.
  const ticking = useRef(false);
  // The note and line a `?line=` was last acted on, so later renders (an
  // edit, a tick) don't scroll back to it.
  const openedAt = useRef<string | null>(null);
  // The note open and the buffer as it is now, for a write's answer to
  // check once it lands: the user may have opened another note or typed
  // while it was in flight.
  const openPath = useRef(path);
  const buffer = useRef(content);
  const editorRef = useRef<HTMLDivElement>(null);
  const { isZen, toggleZen } = useZenMode();
  const { theme, toggleTheme } = useTheme();
  const { isOffline } = useOffline();
  // Every write entry point below is gated on canWrite (online and the
  // vault not read-only). How an unavailable control looks depends on why:
  // hidden on a read-only vault (permanent), disabled offline (temporary).
  const canWrite = useCanWrite();
  const vaultReadOnly = useVaultReadOnly();

  useEffect(() => {
    if (!path) return;
    // Guards against a stale response overwriting a newer one: opening
    // note A (getNote(A) in flight) then quickly navigating to note B
    // before A resolves re-runs this effect for `path=B`, but A's promise
    // is still outstanding. If A later settles (e.g. it's slower under the
    // service worker's networkTimeoutSeconds fallback -- plausible exactly
    // in the flaky-connection conditions this feature targets), its
    // .then()/.catch() must not clobber the state of the now-different,
    // already-loaded note B. Mirrors AuthContext.tsx's mount-effect
    // cancellation pattern (review finding #6, 2026-08-31 code review).
    let cancelled = false;
    openPath.current = path;
    setLoading(true);
    setLoadError(null);
    setSaveError(null);
    setConflictOpen(false);
    setConflictDeleted(false);
    setConflictError(null);
    setTaskNotice(null);
    setTaskError(null);
    setHighlightLine(null);
    setMode("preview");
    getNote(path)
      .then((note) => {
        if (cancelled) return;
        setContent(note.content);
        setSavedContent(note.content);
        setBaseVersion(note.version ?? undefined);
        setTitle(note.title);
        setCreated(note.created);
        setUpdated(note.updated);
      })
      .catch((err) => {
        if (cancelled) return;
        // No prior `.catch()` existed here -- a cache-miss offline (or
        // any other fetch failure) rejected silently, leaving `loading`
        // false but content/title/etc. at their previous stale values
        // (or blank on first load). Surface it explicitly instead.
        setLoadError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [path]);

  const isDirty = content !== savedContent;

  useLayoutEffect(() => {
    buffer.current = content;
  }, [content]);

  // The editor's changes reach the ref at once, not on the next render, so
  // an answer landing in between still sees them.
  const handleEditorChange = useCallback((text: string) => {
    buffer.current = text;
    setContent(text);
  }, []);

  // The note a write or fetch returned, for the buffer `sent` was taken
  // from. The server re-renders frontmatter on a write, so its content, not
  // the buffer's, is the new base. Anything typed since `sent` stays,
  // unsaved, with the note's own change folded in. When the two overlap,
  // nothing is adopted: the base stays where it was, so the next save is
  // refused and the conflict dialog asks, instead of that save silently
  // undoing the note's change. Returns whether the note was adopted.
  const adoptSavedNote = useCallback((note: Note, sent: string): boolean => {
    let next = note.content;
    if (buffer.current !== sent) {
      const merged = mergeNote(sent, buffer.current, note.content);
      if (!merged.ok) return false;
      next = merged.text;
    }
    buffer.current = next;
    setContent(next);
    setSavedContent(note.content);
    setUpdated(note.updated);
    setBaseVersion(note.version);
    return true;
  }, []);

  // A note fetched again replaces the one shown, title included.
  const adoptReloadedNote = useCallback(
    (note: Note, sent: string) => {
      if (!adoptSavedNote(note, sent)) return;
      setTitle(note.title);
      setCreated(note.created);
    },
    [adoptSavedNote],
  );

  // A preview checkbox ticks or unticks its task with a line edit on the
  // server, which only a clean buffer allows (the checkboxes are disabled
  // otherwise). The note it returns becomes the base of the next save, so
  // that save isn't refused because of the tick. When the task isn't where
  // the preview put it any more, nothing is written and the note reloads.
  // An answer that lands once another note is open is dropped.
  const handleToggleTask = useCallback(
    async ({ line, text, done }: { line: number; text: string; done: boolean }) => {
      if (ticking.current || !canWrite || isDirty) return;
      ticking.current = true;
      setTaskNotice(null);
      setTaskError(null);
      const clicked = content;
      const stillOpen = () => openPath.current === path;
      try {
        const { note } = await setTaskDone({
          path,
          line,
          text,
          done,
          date: done ? localIsoDate() : null,
        });
        if (stillOpen()) adoptSavedNote(note, clicked);
      } catch (err) {
        if (!stillOpen()) return;
        if (!isTaskChangedError(err)) {
          setTaskError(errorMessage(err));
          return;
        }
        try {
          const fresh = await getLiveNote(path);
          if (!stillOpen()) return;
          adoptReloadedNote(fresh, clicked);
          setTaskNotice(TASK_CHANGED_MESSAGE);
        } catch (reloadErr) {
          if (!stillOpen()) return;
          // A note that is gone shows as one that can't be opened.
          if (reloadErr instanceof ApiError && reloadErr.status === 404) {
            setLoadError(reloadErr);
          } else {
            setTaskError(saveErrorMessage(reloadErr));
          }
        }
      } finally {
        ticking.current = false;
      }
    },
    [path, content, canWrite, isDirty, adoptSavedNote, adoptReloadedNote],
  );

  // Hidden on a read-only vault (the checkboxes only show their state),
  // disabled offline and while there are unsaved edits.
  const taskToggle = useMemo<TaskToggle | undefined>(
    () =>
      vaultReadOnly
        ? undefined
        : {
            content,
            disabled: !canWrite || isDirty,
            hint: isDirty ? SAVE_FIRST_HINT : null,
            onToggle: handleToggleTask,
          },
    [vaultReadOnly, content, canWrite, isDirty, handleToggleTask],
  );

  // Opening a task from the list (`?line=N`) lands on it in the preview,
  // but only while that file line still holds a task: one that moved opens
  // the note at the top with a notice instead of highlighting the wrong
  // line. Acted on once per note and line.
  useEffect(() => {
    if (loading || loadError || lineToOpen === null || mode !== "preview") return;
    const key = `${path}\n${lineToOpen}`;
    if (openedAt.current === key) return;
    openedAt.current = key;
    if (taskOnLine(content, lineToOpen) === null) {
      setTaskNotice(TASK_MOVED_MESSAGE);
      return;
    }
    setHighlightLine(lineToOpen);
  }, [loading, loadError, lineToOpen, mode, path, content]);

  useEffect(() => {
    if (highlightLine === null) return;
    editorRef.current
      ?.querySelector(`[data-source-line="${highlightLine}"]`)
      ?.scrollIntoView({ block: "center" });
    const timer = window.setTimeout(() => setHighlightLine(null), HIGHLIGHT_MS);
    return () => window.clearTimeout(timer);
  }, [highlightLine]);

  // Every save from the editor goes through here (R16): it names the
  // version the buffer started from, so a file changed elsewhere since is
  // refused rather than overwritten. A refused save is merged with the file
  // as it is now and saved once more; when the changes overlap, or that
  // second save is refused too, the conflict dialog takes over; a note
  // deleted elsewhere can't be merged with, so it asks at once. Throws on
  // any other failure, for the caller to report. Anything typed while the
  // save is in flight stays, unsaved (adoptSavedNote).
  const handleSave = useCallback(async (): Promise<SaveOutcome> => {
    setSaving(true);
    const sent = content;
    try {
      let note: Note;
      try {
        note = await putNote(path, sent, { baseVersion });
      } catch (err) {
        if (!(err instanceof NoteConflictError)) throw err;
        let fresh: Note;
        try {
          // Rejects with CachedNoteError when only the offline cache
          // answers: merging against a copy older than the file would only
          // be refused again, so the buffer stays dirty instead.
          fresh = await getLiveNote(path);
        } catch (fetchErr) {
          if (!(fetchErr instanceof ApiError && fetchErr.status === 404))
            throw fetchErr;
          setConflictDeleted(true);
          setConflictOpen(true);
          return "conflict";
        }
        const merged = mergeNote(savedContent, sent, fresh.content);
        if (!merged.ok) {
          setConflictDeleted(false);
          setConflictOpen(true);
          return "conflict";
        }
        try {
          note = await putNote(path, merged.text, { baseVersion: fresh.version });
        } catch (retryErr) {
          // Changed yet again: one automatic merge only, then ask.
          if (!(retryErr instanceof NoteConflictError)) throw retryErr;
          setConflictDeleted(false);
          setConflictOpen(true);
          return "conflict";
        }
      }
      adoptSavedNote(note, sent);
      return "saved";
    } finally {
      setSaving(false);
    }
  }, [path, content, savedContent, baseVersion, adoptSavedNote]);

  // The Save button's and Cmd+S's entry point: unlike handleSave (which
  // handleBlockedSave needs to throw), reports a failure inline.
  const handleSaveWithError = useCallback(async () => {
    setSaveError(null);
    try {
      await handleSave();
    } catch (err) {
      setSaveError(saveErrorMessage(err));
    }
  }, [handleSave]);

  // Reload: the note as it is now replaces the buffer, whose text moves to
  // the copy panel instead of being lost.
  const handleConflictReload = useCallback(async () => {
    setConflictError(null);
    setSaving(true);
    try {
      const fresh = await getLiveNote(path);
      // All of the buffer, so all of it is replaced.
      const replaced = buffer.current;
      setUnsavedText(replaced);
      adoptReloadedNote(fresh, replaced);
      setSaveError(null);
      setConflictOpen(false);
    } catch (err) {
      setConflictError(saveErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }, [path, adoptReloadedNote]);

  // Keep mine: unconditional on purpose, the user chose to overwrite (or,
  // for a note deleted elsewhere, to save it again).
  const handleConflictKeepMine = useCallback(async () => {
    setConflictError(null);
    setSaving(true);
    try {
      adoptSavedNote(await putNote(path, content), content);
      setSaveError(null);
      setConflictOpen(false);
    } catch (err) {
      setConflictError(saveErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }, [path, content, adoptSavedNote]);

  function handleConflictCancel() {
    setConflictError(null);
    setConflictOpen(false);
  }

  // Warns on tab close/refresh (R2) -- browsers only allow a native,
  // unstyled confirmation here, no custom Save/Discard/Cancel UI is
  // possible (KTD3), unlike the router-navigation case below.
  useEffect(() => {
    function handleBeforeUnload(event: BeforeUnloadEvent) {
      if (!isDirty) return;
      event.preventDefault();
    }
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [isDirty]);

  // Mirror the dirty state into the module-scoped flag ReloadPrompt reads,
  // so a service-worker update can't reload the page over an unsaved
  // buffer (U8 / R15). Clear it when this page unmounts.
  useEffect(() => {
    setEditorDirty(isDirty);
    return () => setEditorDirty(false);
  }, [isDirty]);

  // Intercepts every router-mediated navigation away from a dirty note --
  // sidebar clicks, note-to-note links, graph node clicks, browser
  // back/forward -- regardless of which component triggered it, since
  // useBlocker fires on any attempted route change while this component
  // is mounted (KTD2). Requires the data router migration (KTD1).
  const blocker = useBlocker(isDirty);

  const handleBlockedSave = useCallback(async () => {
    // Mirrors the Cmd+S keydown handler's `if (saving || isOffline) return;`
    // guard below -- this was the one write entry point in the component
    // never gated on isOffline (review finding #8, 2026-08-31 code
    // review), so clicking Save in this dialog while offline still
    // attempted a real putNote() and surfaced a raw fetch-failure message
    // instead of the app's established offline messaging. The dialog's own
    // Save button is now also disabled via the isOffline prop below; this
    // is defense in depth for any other caller of this handler. canWrite
    // also covers a read-only vault.
    if (!canWrite) return;
    setBlockerError(null);
    try {
      const outcome = await handleSave();
      if (blocker.state !== "blocked") return;
      if (outcome === "saved") {
        blocker.proceed();
      } else {
        // Nothing was saved and the conflict dialog is open: stay on the
        // note, where a Reload's copy panel is visible, rather than stack
        // two dialogs over a navigation that would lose it.
        blocker.reset();
      }
    } catch (err) {
      // handleSave's own finally already reset `saving` -- only the
      // dialog's error state is this function's responsibility. Do NOT
      // proceed(): the edit must stay on this note until Save succeeds,
      // Discard is chosen, or Cancel is chosen (R3).
      setBlockerError(saveErrorMessage(err));
    }
  }, [handleSave, blocker, canWrite]);

  function handleBlockedDiscard() {
    setBlockerError(null);
    if (blocker.state === "blocked") blocker.proceed();
  }

  function handleBlockedCancel() {
    setBlockerError(null);
    if (blocker.state === "blocked") blocker.reset();
  }

  // A layout effect, not a plain one: React runs plain effects a moment
  // after the page renders, so a Cmd+S pressed right after a note loads
  // could reach the previous listener, which still holds the content from
  // before the load. A layout effect swaps the listener in during the
  // same commit that shows the new content.
  useLayoutEffect(() => {
    if (!path) return;
    function handleKeyDown(event: KeyboardEvent) {
      const isSaveShortcut =
        (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s";
      if (!isSaveShortcut) return;
      event.preventDefault();
      // A no-op offline, on a read-only vault, with nothing to save, or
      // while the conflict dialog is asking (still preventDefault'ed above,
      // so the browser's own "Save page" never opens).
      if (saving || !canWrite || !isDirty || conflictOpen) return;
      // Route through the dialog's own Save handler while it's blocking
      // navigation, so blocker.proceed()/the dialog's error state stay in
      // sync -- the plain handleSave() never calls blocker.proceed(), so
      // saving via the shortcut while blocked would leave the dialog
      // rendered and stale, still claiming "unsaved changes" for content
      // that's already clean.
      if (blocker.state === "blocked") {
        handleBlockedSave();
      } else {
        handleSaveWithError();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [
    path,
    saving,
    canWrite,
    isDirty,
    conflictOpen,
    handleSaveWithError,
    blocker.state,
    handleBlockedSave,
  ]);

  if (!path) {
    return (
      <p className="empty-hint">Select a note from the sidebar, or create a new one.</p>
    );
  }

  if (loading) {
    return <p className="loading-indicator">Loading...</p>;
  }

  if (loadError) {
    return (
      <p className="error-text" role="alert">
        {isOffline ? "This note isn't available offline." : errorMessage(loadError)}
      </p>
    );
  }

  return (
    <div className="note-view">
      {blocker.state === "blocked" && (
        <UnsavedChangesDialog
          error={blockerError}
          busy={saving}
          isOffline={!canWrite}
          onSave={handleBlockedSave}
          onDiscard={handleBlockedDiscard}
          onCancel={handleBlockedCancel}
        />
      )}
      {conflictOpen && (
        <SaveConflictDialog
          deleted={conflictDeleted}
          error={conflictError}
          busy={saving}
          isOffline={!canWrite}
          onReload={handleConflictReload}
          onKeepMine={handleConflictKeepMine}
          onCancel={handleConflictCancel}
        />
      )}
      <div className="note-editor" ref={editorRef}>
        <NotePathHeader
          path={path}
          title={title}
          created={created}
          updated={updated}
          onRenamed={(updatedNote) => {
            setContent(updatedNote.content);
            setSavedContent(updatedNote.content);
            // A rename rewrites the file, so its old version would refuse
            // the next save.
            setBaseVersion(updatedNote.version);
            setTitle(updatedNote.title);
            setUpdated(updatedNote.updated);
            if (updatedNote.path !== path) {
              navigate(`/notes/${encodeNotePath(updatedNote.path)}`);
            }
          }}
          onDeleted={() => navigate("/")}
          readOnly={!canWrite}
          actions={
            <>
              <button
                type="button"
                className="btn btn-sm theme-toggle"
                aria-pressed={theme === "dark"}
                onClick={toggleTheme}
              >
                {theme === "dark" ? "Light" : "Dark"}
              </button>
              <button
                type="button"
                className="btn btn-sm zen-toggle"
                aria-pressed={isZen}
                onClick={toggleZen}
              >
                {isZen ? "Exit Zen mode" : "Zen mode"}
              </button>
            </>
          }
        />

        {taskNotice && (
          <p className="note-notice" role="status">
            {taskNotice}
          </p>
        )}
        {taskError && (
          <p className="error-text" role="alert">
            {taskError}
          </p>
        )}

        {mode === "edit" ? (
          <MarkdownEditor
            value={content}
            onChange={handleEditorChange}
            currentPath={path}
            readOnly={!canWrite}
          />
        ) : (
          <MarkdownPreview
            body={stripFrontmatter(content)}
            lineOffset={frontmatterLineCount(content)}
            currentPath={path}
            tasks={taskToggle}
            highlightLine={highlightLine}
          />
        )}

        <div className="note-editor-actions">
          {/* "Saved" means nothing on a vault that can't be written; an
              edit already in flight when read-only arrives still says so. */}
          {(isDirty || !vaultReadOnly) && (
            <span className="save-status">{isDirty ? "Unsaved changes" : "Saved"}</span>
          )}
          {!vaultReadOnly && (
            <span className="shortcut-hint">
              <kbd>{isMac ? "⌘" : "Ctrl"}</kbd>+<kbd>S</kbd> to save
            </span>
          )}
          <span className="chrome-spacer" />
          {mode === "edit" ? (
            <>
              <button type="button" className="btn" onClick={() => setMode("preview")}>
                Preview
              </button>
              {!vaultReadOnly && (
                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={handleSaveWithError}
                  disabled={saving || isOffline}
                >
                  {saving ? "Saving..." : "Save"}
                </button>
              )}
            </>
          ) : (
            !vaultReadOnly && (
              <button
                type="button"
                className="btn btn-edit"
                onClick={() => setMode("edit")}
                disabled={isOffline}
              >
                Edit
              </button>
            )
          )}
        </div>
        {saveError && (
          <p className="error-text save-error" role="alert">
            {saveError}
          </p>
        )}
        {unsavedText !== null && (
          <UnsavedTextPanel text={unsavedText} onDismiss={() => setUnsavedText(null)} />
        )}
      </div>
      <aside className="note-backlinks">
        <h2>Backlinks</h2>
        <BacklinksPanel path={path} />
      </aside>
    </div>
  );
}

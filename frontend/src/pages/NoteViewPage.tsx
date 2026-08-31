import { useCallback, useEffect, useState } from "react";
import { useBlocker, useNavigate, useParams } from "react-router-dom";
import { encodeNotePath, errorMessage, getNote, putNote } from "../api/client";
import { BacklinksPanel } from "../components/Backlinks/BacklinksPanel";
import { UnsavedChangesDialog } from "../components/ConfirmDialog/UnsavedChangesDialog";
import { MarkdownEditor } from "../components/Editor/MarkdownEditor";
import { MarkdownPreview } from "../components/Editor/MarkdownPreview";
import { NotePathHeader } from "../components/Editor/NotePathHeader";
import { useOffline } from "../context/OfflineContext";
import { useTheme } from "../context/ThemeContext";
import { useZenMode } from "../context/ZenModeContext";
import { stripFrontmatter } from "../lib/noteContent";

type ViewMode = "edit" | "preview";

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
  const [content, setContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [title, setTitle] = useState("");
  const [created, setCreated] = useState<string | null>(null);
  const [updated, setUpdated] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [mode, setMode] = useState<ViewMode>("preview");
  const [blockerError, setBlockerError] = useState<string | null>(null);
  // Holds the raw fetch failure, not a pre-formatted message -- whether to
  // show the offline-specific copy or the raw error text is decided at
  // render time from the *current* `isOffline`, not baked in when the
  // catch fires. That also keeps `isOffline` out of this effect's own
  // dependency list below, which matters: this effect should only re-run
  // when `path` changes (a new note being opened), not every time
  // connectivity flips mid-fetch -- refetching on every online/offline
  // toggle would fight the in-flight request.
  const [loadError, setLoadError] = useState<unknown>(null);
  const { isZen, toggleZen } = useZenMode();
  const { theme, toggleTheme } = useTheme();
  const { isOffline } = useOffline();

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
    setLoading(true);
    setLoadError(null);
    setMode("preview");
    getNote(path)
      .then((note) => {
        if (cancelled) return;
        setContent(note.content);
        setSavedContent(note.content);
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

  const handleSave = useCallback(async () => {
    setSaving(true);
    try {
      const note = await putNote(path, content);
      setSavedContent(note.content);
      setContent(note.content);
      setUpdated(note.updated);
    } finally {
      setSaving(false);
    }
  }, [path, content]);

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
    // is defense in depth for any other caller of this handler.
    if (isOffline) return;
    setBlockerError(null);
    try {
      await handleSave();
      if (blocker.state === "blocked") blocker.proceed();
    } catch (err) {
      // handleSave's own finally already reset `saving` -- only the
      // dialog's error state is this function's responsibility. Do NOT
      // proceed(): the edit must stay on this note until Save succeeds,
      // Discard is chosen, or Cancel is chosen (R3).
      setBlockerError(errorMessage(err));
    }
  }, [handleSave, blocker, isOffline]);

  function handleBlockedDiscard() {
    setBlockerError(null);
    if (blocker.state === "blocked") blocker.proceed();
  }

  function handleBlockedCancel() {
    setBlockerError(null);
    if (blocker.state === "blocked") blocker.reset();
  }

  useEffect(() => {
    if (!path) return;
    function handleKeyDown(event: KeyboardEvent) {
      const isSaveShortcut =
        (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s";
      if (!isSaveShortcut) return;
      event.preventDefault();
      if (saving || isOffline) return;
      // Route through the dialog's own Save handler while it's blocking
      // navigation, so blocker.proceed()/the dialog's error state stay in
      // sync -- the plain handleSave() never calls blocker.proceed(), so
      // saving via the shortcut while blocked would leave the dialog
      // rendered and stale, still claiming "unsaved changes" for content
      // that's already clean.
      if (blocker.state === "blocked") {
        handleBlockedSave();
      } else {
        handleSave();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [path, saving, isOffline, handleSave, blocker.state, handleBlockedSave]);

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
          isOffline={isOffline}
          onSave={handleBlockedSave}
          onDiscard={handleBlockedDiscard}
          onCancel={handleBlockedCancel}
        />
      )}
      <div className="note-editor">
        <NotePathHeader
          path={path}
          title={title}
          created={created}
          updated={updated}
          onRenamed={(updatedNote) => {
            setContent(updatedNote.content);
            setSavedContent(updatedNote.content);
            setTitle(updatedNote.title);
            setUpdated(updatedNote.updated);
            if (updatedNote.path !== path) {
              navigate(`/notes/${encodeNotePath(updatedNote.path)}`);
            }
          }}
          onDeleted={() => navigate("/")}
          isOffline={isOffline}
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

        {mode === "edit" ? (
          <MarkdownEditor
            value={content}
            onChange={setContent}
            currentPath={path}
            readOnly={isOffline}
          />
        ) : (
          <MarkdownPreview body={stripFrontmatter(content)} currentPath={path} />
        )}

        <div className="note-editor-actions">
          <span className="save-status">{isDirty ? "Unsaved changes" : "Saved"}</span>
          <span className="shortcut-hint">
            <kbd>{isMac ? "⌘" : "Ctrl"}</kbd>+<kbd>S</kbd> to save
          </span>
          <span className="chrome-spacer" />
          {mode === "edit" ? (
            <>
              <button type="button" className="btn" onClick={() => setMode("preview")}>
                Preview
              </button>
              <button
                type="button"
                className="btn btn-primary"
                onClick={handleSave}
                disabled={saving || isOffline}
              >
                {saving ? "Saving..." : "Save"}
              </button>
            </>
          ) : (
            <button
              type="button"
              className="btn btn-edit"
              onClick={() => setMode("edit")}
              disabled={isOffline}
            >
              Edit
            </button>
          )}
        </div>
      </div>
      <aside className="note-backlinks">
        <h2>Backlinks</h2>
        <BacklinksPanel path={path} />
      </aside>
    </div>
  );
}

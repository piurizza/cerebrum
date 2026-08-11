import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  encodeNotePath,
  errorMessage,
  getNote,
  putNote,
  searchNotes,
} from "../../api/client";
import { useNotes } from "../../context/NotesContext";
import { getDailyNoteDefaultBody, getTodayNotePath } from "../../lib/dailyNote";
import { stripTemplateIdentityFields } from "../../lib/noteContent";
import { buildNoteTree, splitNotePath } from "../../lib/noteTree";
import type { TemplateOption } from "../../lib/templates";
import { hasRelevantTemplate, listTemplateOptions } from "../../lib/templates";
import type { NoteMeta } from "../../types/note";
import { FolderPickerModal } from "../FolderPicker/FolderPickerModal";
import { TemplatePickerModal } from "../TemplatePicker/TemplatePickerModal";
import { NoteTreeList } from "./NoteTreeList";

const SEARCH_DEBOUNCE_MS = 250;

export function NoteBrowser() {
  const { notes, error, loading, refreshNotes } = useNotes();
  const [isPickerOpen, setIsPickerOpen] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const [todayError, setTodayError] = useState<string | null>(null);
  const [isOpeningToday, setIsOpeningToday] = useState(false);
  // One atom, not two: `path` and `options` are only ever set or cleared
  // together (there is no state where one is stale while the other is
  // current), so splitting them invites drift.
  const [pendingCreate, setPendingCreate] = useState<{
    path: string;
    options: TemplateOption[];
  } | null>(null);
  const [templateError, setTemplateError] = useState<string | null>(null);
  const [isCreatingNote, setIsCreatingNote] = useState(false);
  const [collapsedFolders, setCollapsedFolders] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<NoteMeta[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [selectedTag, setSelectedTag] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const trimmed = query.trim();
    if (!trimmed) {
      setResults(null);
      setSearching(false);
      return;
    }
    setSearching(true);
    const handle = window.setTimeout(() => {
      searchNotes(trimmed)
        .then(setResults)
        .catch(() => setResults([]))
        .finally(() => setSearching(false));
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(handle);
  }, [query]);

  // Titles aren't unique -- two notes in different folders can share a
  // title. Only show the disambiguating path for titles that actually
  // collide, so the common case (unique titles) stays uncluttered.
  const duplicateTitles = useMemo(() => {
    const counts = new Map<string, number>();
    for (const note of notes) {
      counts.set(note.title, (counts.get(note.title) ?? 0) + 1);
    }
    return new Set(
      [...counts.entries()].filter(([, count]) => count > 1).map(([title]) => title),
    );
  }, [notes]);

  const allTags = useMemo(() => {
    const tags = new Set<string>();
    for (const note of notes) {
      for (const tag of note.tags) tags.add(tag);
    }
    return [...tags].sort();
  }, [notes]);

  const tagFilteredNotes = useMemo(
    () =>
      selectedTag ? notes.filter((note) => note.tags.includes(selectedTag)) : notes,
    [notes, selectedTag],
  );

  const tree = useMemo(() => buildNoteTree(tagFilteredNotes), [tagFilteredNotes]);
  const searchResultNodes = useMemo(
    () => (results ?? []).map((note) => ({ type: "note" as const, note })),
    [results],
  );

  function toggleFolder(folderPath: string) {
    setCollapsedFolders((current) => {
      const next = new Set(current);
      if (next.has(folderPath)) {
        next.delete(folderPath);
      } else {
        next.add(folderPath);
      }
      return next;
    });
  }

  function noteExistsAt(path: string): boolean {
    return notes.some((note) => note.path === path);
  }

  function noteExistsErrorText(path: string): string {
    return `A note already exists at "${path}".`;
  }

  // If no template is relevant to this folder (R3's skip rule), this is
  // byte-for-byte the pre-templates create flow -- R4's backward-compat
  // floor. Otherwise, hand off to TemplatePickerModal via
  // handleTemplateConfirm instead of writing here.
  async function handleCreate(path: string) {
    setCreateError(null);

    const options = listTemplateOptions(notes, splitNotePath(path).folder);
    if (hasRelevantTemplate(options)) {
      setIsPickerOpen(false);
      setPendingCreate({ path, options });
      return;
    }

    if (noteExistsAt(path)) {
      setCreateError(noteExistsErrorText(path));
      return;
    }

    try {
      await putNote(path, "");
    } catch (err) {
      setCreateError(errorMessage(err));
      return;
    }

    setIsPickerOpen(false);
    refreshNotes();
    navigate(`/notes/${encodeNotePath(path)}`);
  }

  // `templatePath === null` means "Blank note" -- identical to
  // handleCreate's blank path above. Re-checks noteExistsAt against the
  // pending path here too, since a template selection must not bypass
  // that guard. On error the modal stays open (pendingCreate untouched)
  // so the user can retry or pick a different template -- errors
  // surface via TemplatePickerModal's own `error` prop, never
  // NoteBrowser's top-level `createError` (which would replace the
  // whole sidebar via the early `return` above).
  async function handleTemplateConfirm(templatePath: string | null) {
    if (!pendingCreate) return;
    const { path } = pendingCreate;

    if (noteExistsAt(path)) {
      setTemplateError(noteExistsErrorText(path));
      return;
    }

    setTemplateError(null);
    setIsCreatingNote(true);
    try {
      const content = templatePath
        ? stripTemplateIdentityFields((await getNote(templatePath)).content)
        : "";
      await putNote(path, content);
      await refreshNotes();
      setPendingCreate(null);
      navigate(`/notes/${encodeNotePath(path)}`);
    } catch (err) {
      setTemplateError(errorMessage(err));
    } finally {
      setIsCreatingNote(false);
    }
  }

  function handleTemplateCancel() {
    setPendingCreate(null);
    setTemplateError(null);
  }

  // Unlike handleCreate, an existing path is success here, not an error:
  // navigate straight to it and never call putNote, so existing content
  // is never touched (R1's "never overwrite" requirement).
  async function handleToday() {
    // A single shared `now` for both calls below -- computing the path
    // and the heading from two independent `new Date()` calls could let
    // a local-midnight rollover between them produce a path and heading
    // for different days.
    const now = new Date();
    const path = getTodayNotePath(now);

    if (noteExistsAt(path)) {
      navigate(`/notes/${encodeNotePath(path)}`);
      return;
    }

    setTodayError(null);
    setIsOpeningToday(true);
    try {
      await putNote(path, getDailyNoteDefaultBody(now));
      // Awaited, not fire-and-forget: the button re-enables in `finally`
      // below right after this resolves, and the sidebar never unmounts
      // on navigate (it's outside <Routes>) -- without awaiting, a
      // re-click landing in the gap between "button re-enabled" and
      // "notes list actually reflects the new note" would re-run this
      // branch and overwrite whatever the user just started typing.
      await refreshNotes();
      navigate(`/notes/${encodeNotePath(path)}`);
    } catch (err) {
      setTodayError(errorMessage(err));
    } finally {
      setIsOpeningToday(false);
    }
  }

  if (error) {
    return (
      <p className="error-text" role="alert">
        Failed to load notes: {error}
      </p>
    );
  }

  return (
    <nav aria-label="Notes" className="note-browser">
      <button
        type="button"
        className="btn btn-block"
        onClick={handleToday}
        disabled={loading || isOpeningToday}
      >
        Today
      </button>
      {todayError && (
        <p className="error-text" role="alert">
          {todayError}
        </p>
      )}
      <button
        type="button"
        className="btn btn-block"
        onClick={() => {
          setCreateError(null);
          setIsPickerOpen(true);
        }}
      >
        + New note
      </button>
      {isPickerOpen && (
        <FolderPickerModal
          title="New note"
          initialPath=""
          confirmLabel="Create"
          error={createError}
          onConfirm={handleCreate}
          onCancel={() => setIsPickerOpen(false)}
        />
      )}
      {pendingCreate && (
        <TemplatePickerModal
          title="Choose a template"
          options={pendingCreate.options}
          pending={isCreatingNote}
          error={templateError}
          onConfirm={handleTemplateConfirm}
          onCancel={handleTemplateCancel}
        />
      )}
      <input
        type="search"
        className="search-input"
        placeholder="Search notes..."
        value={query}
        onChange={(event) => setQuery(event.target.value)}
      />
      {results === null && allTags.length > 0 && (
        <div className="tag-filter">
          {allTags.map((tag) => (
            <button
              key={tag}
              type="button"
              className={selectedTag === tag ? "tag-pill is-active" : "tag-pill"}
              onClick={() => setSelectedTag(selectedTag === tag ? null : tag)}
            >
              {tag}
            </button>
          ))}
        </div>
      )}
      {results !== null ? (
        searching ? (
          <p className="loading-indicator">Searching...</p>
        ) : results.length === 0 ? (
          <p className="empty-hint">No matches for "{query.trim()}".</p>
        ) : (
          <NoteTreeList
            nodes={searchResultNodes}
            duplicateTitles={duplicateTitles}
            collapsedFolders={collapsedFolders}
            onToggleFolder={toggleFolder}
          />
        )
      ) : notes.length === 0 ? (
        <p className="empty-hint">No notes yet.</p>
      ) : tagFilteredNotes.length === 0 ? (
        <p className="empty-hint">No notes tagged "{selectedTag}".</p>
      ) : (
        <NoteTreeList
          nodes={tree}
          duplicateTitles={duplicateTitles}
          collapsedFolders={collapsedFolders}
          onToggleFolder={toggleFolder}
        />
      )}
    </nav>
  );
}

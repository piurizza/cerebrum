import { useEffect, useId, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { encodeNotePath } from "../api/client";
import { useNotes } from "../context/NotesContext";
import { useTagSelection } from "../context/TagSelectionContext";
import { MOBILE_QUERY, useMediaQuery } from "../hooks/useMediaQuery";
import { formatRelativeDate } from "../lib/formatDate";
import { splitNotePath } from "../lib/noteTree";
import {
  collectTagCounts,
  normalizeTag,
  noteMatchesTags,
  type TagCount,
} from "../lib/tagQuery";
import type { NoteMeta } from "../types/note";

interface TagGroup {
  parent: TagCount;
  children: TagCount[];
}

// One group per top-level tag, its nested tags on a line beneath it. The
// filter keeps a parent visible when only one of its children matches.
function groupTags(counts: readonly TagCount[], filter: string): TagGroup[] {
  const wanted = filter.trim().toLowerCase();
  const groups = new Map<string, TagGroup>();
  for (const entry of counts) {
    const top = entry.key.split("/")[0];
    if (entry.key === top) {
      groups.set(top, { parent: entry, children: [] });
    } else {
      groups.get(top)?.children.push(entry);
    }
  }
  return [...groups.values()].flatMap((group) => {
    if (!wanted || group.parent.key.includes(wanted)) return [group];
    const children = group.children.filter((child) => child.key.includes(wanted));
    return children.length > 0 ? [{ ...group, children }] : [];
  });
}

// Newest first by the parsed date: frontmatter dates mix offsets and
// date-only values, so comparing the strings would misorder them.
function byUpdatedDesc(a: NoteMeta, b: NoteMeta): number {
  const time = (note: NoteMeta) =>
    note.updated ? Date.parse(note.updated) : Number.NaN;
  const [aTime, bTime] = [time(a), time(b)];
  if (Number.isNaN(aTime) !== Number.isNaN(bTime)) return Number.isNaN(aTime) ? 1 : -1;
  if (!Number.isNaN(aTime) && aTime !== bTime) return bTime - aTime;
  return a.path.localeCompare(b.path);
}

/** The front page: every tag with its note count, and the notes matching
 * the tags picked -- the same selection as the sidebar search box's chips.
 * On a phone the tag list makes room for the results once something is
 * picked; wider, the two sit side by side. */
export function HomePage() {
  const { notes, error, loading } = useNotes();
  const { chips, toggleInclude, removeChip, clearChips } = useTagSelection();
  const isMobile = useMediaQuery(MOBILE_QUERY);
  const [filter, setFilter] = useState("");
  // Opened with the toggle, the list stays open for further taps until
  // hidden again; otherwise the first pick collapses it.
  const [indexOpen, setIndexOpen] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const focusToggle = useRef(false);
  const indexId = useId();

  const counts = useMemo(() => collectTagCounts(notes, chips), [notes, chips]);
  const groups = useMemo(() => groupTags(counts, filter), [counts, filter]);
  const results = useMemo(
    () =>
      chips.length > 0
        ? notes.filter((note) => noteMatchesTags(note.tags, chips)).sort(byUpdatedDesc)
        : [],
    [notes, chips],
  );
  const chosen = useMemo(
    () => new Map(chips.map((chip) => [normalizeTag(chip.tag), chip])),
    [chips],
  );
  const indexHidden = isMobile && chips.length > 0 && !indexOpen;

  useEffect(() => {
    if (chips.length === 0) setIndexOpen(false);
  }, [chips.length]);

  useEffect(() => {
    if (focusToggle.current && indexHidden) toggleRef.current?.focus();
    focusToggle.current = false;
  });

  function handleTag(entry: TagCount) {
    if (chips.length === 0) focusToggle.current = true;
    toggleInclude(entry.tag);
  }

  if (error) {
    return (
      <p className="error-text" role="alert">
        Failed to load notes: {error}
      </p>
    );
  }
  if (loading) return <p className="loading-indicator">Loading notes...</p>;
  if (notes.length === 0) return <p className="empty-hint">No notes yet.</p>;

  function tagButton(entry: TagCount, label: string) {
    const chip = chosen.get(entry.key);
    const selected = chip !== undefined && !chip.excluded;
    return (
      <button
        key={entry.key}
        type="button"
        className={selected ? "tag-pill is-active" : "tag-pill"}
        aria-pressed={selected}
        aria-label={`${entry.tag} (${entry.count} ${entry.count === 1 ? "note" : "notes"})`}
        disabled={!chip && chips.length > 0 && entry.count === 0}
        onClick={() => handleTag(entry)}
      >
        {label} <span className="tag-count">{entry.count}</span>
      </button>
    );
  }

  return (
    <div className="home-page">
      <h1>Tags</h1>
      {counts.length === 0 ? (
        <p className="empty-hint">
          No tags yet. Add a <code>tags:</code> list to a note's frontmatter to browse
          by tag here.
        </p>
      ) : (
        <>
          {chips.length > 0 && (
            <div className="tag-selected">
              {chips.map((chip) => (
                <span
                  key={normalizeTag(chip.tag)}
                  className={chip.excluded ? "tag-chip is-excluded" : "tag-chip"}
                >
                  <span className="tag-chip-label">
                    {chip.excluded ? "−" : "#"}
                    {chip.tag}
                  </span>
                  <button
                    type="button"
                    aria-label={
                      chip.excluded
                        ? `Remove excluded tag ${chip.tag}`
                        : `Remove tag ${chip.tag}`
                    }
                    onClick={() => removeChip(chip.tag)}
                  >
                    ×
                  </button>
                </span>
              ))}
              <button type="button" className="btn btn-sm" onClick={clearChips}>
                Clear
              </button>
              {isMobile && (
                <button
                  ref={toggleRef}
                  type="button"
                  className="btn btn-sm"
                  aria-expanded={!indexHidden}
                  aria-controls={indexId}
                  onClick={() => setIndexOpen((open) => !open)}
                >
                  {indexHidden ? `Show all tags (${counts.length})` : "Hide tags"}
                </button>
              )}
            </div>
          )}
          <div className={chips.length > 0 ? "tag-home has-selection" : "tag-home"}>
            <section
              id={indexId}
              className="tag-index"
              aria-label="All tags"
              hidden={indexHidden}
            >
              <input
                type="search"
                className="tag-index-filter"
                aria-label="Filter tags"
                placeholder="Filter tags"
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
              />
              <ul className="tag-groups">
                {groups.map((group) => (
                  <li key={group.parent.key} className="tag-group">
                    {tagButton(group.parent, group.parent.tag)}
                    {group.children.length > 0 && (
                      <div className="tag-group-children">
                        {group.children.map((child) =>
                          tagButton(
                            child,
                            child.tag.slice(group.parent.key.length + 1),
                          ),
                        )}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
              <p className="tag-hint">
                {isMobile
                  ? "Tip: open the menu and type # in the search box to mix tags with words, or -# to leave a tag out."
                  : "Tip: type # in the sidebar search box to mix tags with words, or -# to leave a tag out."}
              </p>
            </section>
            {chips.length > 0 && (
              <section className="tag-results" aria-label="Matching notes">
                {results.length === 0 ? (
                  <p className="empty-hint">
                    No notes match{" "}
                    {chips
                      .map((chip) => `${chip.excluded ? "-" : ""}#${chip.tag}`)
                      .join(" ")}
                    .
                  </p>
                ) : (
                  <ul className="tag-result-list">
                    {results.map((note) => {
                      const { folder } = splitNotePath(note.path);
                      const updated = formatRelativeDate(note.updated);
                      return (
                        <li key={note.path}>
                          <Link
                            className="tag-result"
                            to={`/notes/${encodeNotePath(note.path)}`}
                          >
                            <span className="tag-result-title">{note.title}</span>
                            <span className="tag-result-meta">
                              {[folder, updated].filter(Boolean).join(" · ")}
                            </span>
                          </Link>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </section>
            )}
          </div>
        </>
      )}
    </div>
  );
}

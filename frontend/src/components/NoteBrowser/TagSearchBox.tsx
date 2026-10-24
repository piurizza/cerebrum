import {
  type ChangeEvent,
  type KeyboardEvent,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useTagSelection } from "../../context/TagSelectionContext";
import {
  normalizeTag,
  suggestTags,
  type TagCount,
  tagFragmentAt,
} from "../../lib/tagQuery";
import { TagChip } from "../TagChip";

interface TagSearchBoxProps {
  /** Every tag in the vault with its count (`collectTagCounts`). */
  counts: TagCount[];
  /** The typed text that counts toward the query: everything except the
   * tag still being typed at the caret, which only drives suggestions. */
  onQueryTextChange: (text: string) => void;
}

function joinAround(text: string, start: number, end: number): string {
  const before = text.slice(0, start);
  const after = text.slice(end);
  return before.endsWith(" ") || before === ""
    ? before + after.trimStart()
    : before + after;
}

/** The sidebar search box: words for the full-text search, plus tags as
 * removable chips. Typing `#` (or `-#` to exclude) opens a list of tags
 * with their note counts -- a WAI-ARIA 1.2 combobox. The chips are the
 * shared `TagSelectionContext` selection, so the front page sees them too. */
export function TagSearchBox({ counts, onQueryTextChange }: TagSearchBoxProps) {
  const { chips, addChip, removeChip } = useTagSelection();
  const [text, setText] = useState("");
  const [caret, setCaret] = useState(0);
  const [focused, setFocused] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  // Where to put the caret after a pick rewrites the text.
  const pendingCaret = useRef<number | null>(null);
  const listId = useId();

  // The tag at the caret never filters, focused or not: applying it on
  // blur would reflow the tree under a click on one of its notes. It
  // starts filtering once finished with a space, picked, or left behind
  // by moving the caret.
  const fragment = tagFragmentAt(text, caret);
  const suggestions =
    focused && fragment ? suggestTags(counts, fragment.fragment, chips) : [];
  const listVisible = focused && fragment !== null && !dismissed && counts.length > 0;
  const expanded = listVisible && suggestions.length > 0;
  const active = Math.min(activeIndex, suggestions.length - 1);
  const queryText = fragment ? joinAround(text, fragment.start, fragment.end) : text;

  useEffect(() => {
    onQueryTextChange(queryText);
  }, [queryText, onQueryTextChange]);

  useLayoutEffect(() => {
    if (pendingCaret.current === null || !inputRef.current) return;
    inputRef.current.setSelectionRange(pendingCaret.current, pendingCaret.current);
    pendingCaret.current = null;
  });

  function update(value: string, at: number) {
    setText(value);
    setCaret(at);
    setDismissed(false);
    setActiveIndex(0);
  }

  function pick(entry: TagCount) {
    if (!fragment) return;
    addChip(entry.tag, fragment.excluded);
    const value = joinAround(text, fragment.start, fragment.end);
    pendingCaret.current = fragment.start;
    update(value, fragment.start);
    inputRef.current?.focus();
  }

  function handleChange(event: ChangeEvent<HTMLInputElement>) {
    const { value } = event.target;
    const at = event.target.selectionStart ?? value.length;
    // A space right after a finished `#tag` or `-#tag` the vault knows
    // turns it into a chip; an unknown one stays text (and still filters).
    if (at > 0 && /\s/.test(value[at - 1])) {
      const typed = tagFragmentAt(value, at - 1);
      // Inside `#"two words` the space belongs to the tag.
      const known =
        typed &&
        !typed.quoted &&
        typed.fragment &&
        counts.find((entry) => entry.key === normalizeTag(typed.fragment));
      if (typed && known) {
        addChip(known.tag, typed.excluded);
        const rest = value.slice(0, typed.start) + value.slice(at);
        pendingCaret.current = typed.start;
        update(rest, typed.start);
        return;
      }
    }
    update(value, at);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (expanded) {
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        const step = event.key === "ArrowDown" ? 1 : -1;
        setActiveIndex((active + step + suggestions.length) % suggestions.length);
        return;
      }
      if (event.key === "Enter" || event.key === "Tab") {
        event.preventDefault();
        pick(suggestions[active]);
        return;
      }
    }
    if (event.key === "Escape" && listVisible) {
      // Without this, `type="search"` clears the text natively and the
      // mobile drawer's document listener (App.tsx) closes the drawer.
      event.preventDefault();
      event.stopPropagation();
      setDismissed(true);
      return;
    }
    if (event.key === "Backspace" && text === "" && chips.length > 0) {
      removeChip(chips[chips.length - 1].tag);
    }
  }

  const optionId = (index: number) => `${listId}-option-${index}`;

  return (
    <div className="search-box-wrap">
      {/* biome-ignore lint/a11y/noStaticElementInteractions: clicking the
          padding around the chips focuses the input; the input itself is
          the keyboard target. */}
      {/* biome-ignore lint/a11y/useKeyWithClickEvents: see above. */}
      <div className="search-box" onClick={() => inputRef.current?.focus()}>
        {chips.map((chip) => (
          <TagChip
            key={normalizeTag(chip.tag)}
            chip={chip}
            onRemove={() => {
              removeChip(chip.tag);
              inputRef.current?.focus();
            }}
          />
        ))}
        <input
          ref={inputRef}
          type="search"
          className="search-box-input"
          role="combobox"
          aria-label="Search notes"
          aria-autocomplete="list"
          aria-expanded={expanded}
          aria-controls={listId}
          aria-activedescendant={expanded ? optionId(active) : undefined}
          placeholder={chips.length > 0 ? undefined : "Search notes or #tag"}
          value={text}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          onSelect={(event) => setCaret(event.currentTarget.selectionStart ?? 0)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
        />
      </div>
      {expanded && (
        <div id={listId} role="listbox" aria-label="Tags" className="tag-suggestions">
          {suggestions.map((entry, index) => (
            // Keyboard selection goes through the input (aria-activedescendant),
            // so options are focusable but out of the tab order; mousedown is
            // cancelled so a click never steals the input's focus.
            // biome-ignore lint/a11y/useKeyWithClickEvents: see above.
            <div
              key={entry.key}
              id={optionId(index)}
              role="option"
              tabIndex={-1}
              aria-selected={index === active}
              className={index === active ? "tag-option is-active" : "tag-option"}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => pick(entry)}
            >
              <span>{entry.tag}</span>
              <span className="tag-count">{entry.count}</span>
            </div>
          ))}
        </div>
      )}
      {listVisible && suggestions.length === 0 && (
        <p className="tag-suggestions tag-suggestions-empty">No matching tags</p>
      )}
    </div>
  );
}

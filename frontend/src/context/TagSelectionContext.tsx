import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";
import { normalizeTag, type TagChip } from "../lib/tagQuery";

interface TagSelectionValue {
  /** The tags picked in the sidebar search box or on the front page --
   * one selection shared by both, kept across navigation but not reloads. */
  chips: TagChip[];
  /** Adds a chip, replacing any chip for the same tag (in either polarity). */
  addChip: (tag: string, excluded: boolean) => void;
  removeChip: (tag: string) => void;
  /** The front page's toggle: adds an include chip, removes one, or turns
   * an exclusion into an include. */
  toggleInclude: (tag: string) => void;
  clearChips: () => void;
}

const TagSelectionContext = createContext<TagSelectionValue | null>(null);

function without(chips: TagChip[], tag: string): TagChip[] {
  const key = normalizeTag(tag);
  return chips.filter((chip) => normalizeTag(chip.tag) !== key);
}

export function TagSelectionProvider({ children }: { children: ReactNode }) {
  const [chips, setChips] = useState<TagChip[]>([]);

  const addChip = useCallback((tag: string, excluded: boolean) => {
    setChips((current) => [...without(current, tag), { tag, excluded }]);
  }, []);

  const removeChip = useCallback((tag: string) => {
    setChips((current) => without(current, tag));
  }, []);

  const toggleInclude = useCallback((tag: string) => {
    setChips((current) => {
      const key = normalizeTag(tag);
      const existing = current.find((chip) => normalizeTag(chip.tag) === key);
      if (existing && !existing.excluded) return without(current, tag);
      return [...without(current, tag), { tag, excluded: false }];
    });
  }, []);

  const clearChips = useCallback(() => setChips([]), []);

  const value = useMemo(
    () => ({ chips, addChip, removeChip, toggleInclude, clearChips }),
    [chips, addChip, removeChip, toggleInclude, clearChips],
  );

  return (
    <TagSelectionContext.Provider value={value}>
      {children}
    </TagSelectionContext.Provider>
  );
}

export function useTagSelection(): TagSelectionValue {
  const value = useContext(TagSelectionContext);
  if (!value) {
    throw new Error("useTagSelection must be used within a TagSelectionProvider");
  }
  return value;
}

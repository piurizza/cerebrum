import type { TagChip as TagChipValue } from "../lib/tagQuery";

/** One picked tag with its remove button -- `#work`, or `−archive` struck
 * through when it is left out. Shared by the sidebar search box and the
 * front page, which show the same selection. */
export function TagChip({
  chip,
  onRemove,
}: {
  chip: TagChipValue;
  onRemove: () => void;
}) {
  return (
    <span className={chip.excluded ? "tag-chip is-excluded" : "tag-chip"}>
      <span className="tag-chip-label">
        {chip.excluded ? "−" : "#"}
        {chip.tag}
      </span>
      <button
        type="button"
        aria-label={
          chip.excluded ? `Remove excluded tag ${chip.tag}` : `Remove tag ${chip.tag}`
        }
        onClick={onRemove}
      >
        ×
      </button>
    </span>
  );
}

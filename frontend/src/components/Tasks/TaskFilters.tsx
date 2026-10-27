interface TaskFiltersProps {
  /** The folders that hold tasks (see `taskFolders`). */
  folders: readonly string[];
  folder: string;
  words: string;
  onFolderChange: (folder: string) => void;
  onWordsChange: (words: string) => void;
}

/** The Tasks page's own filters, beside the shared tag selection: a
 * folder (subfolders included) and words in the task text, applied as
 * they are typed. Both are the page's state, gone once it is left. */
export function TaskFilters({
  folders,
  folder,
  words,
  onFolderChange,
  onWordsChange,
}: TaskFiltersProps) {
  // A folder picked before its last task went keeps its option, so the
  // select still shows what the list is filtered by.
  const options = folder && !folders.includes(folder) ? [...folders, folder] : folders;
  return (
    <div className="task-filters">
      <select
        className="task-filter-folder"
        aria-label="Folder"
        value={folder}
        onChange={(event) => onFolderChange(event.target.value)}
      >
        <option value="">All folders</option>
        {options.map((name) => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </select>
      <input
        type="search"
        className="task-filter-words"
        aria-label="Filter by words"
        placeholder="Filter by words"
        value={words}
        onChange={(event) => onWordsChange(event.target.value)}
      />
    </div>
  );
}

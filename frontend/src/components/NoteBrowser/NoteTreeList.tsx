import { NavLink } from "react-router-dom";
import { encodeNotePath } from "../../api/client";
import type { TreeNode } from "../../lib/noteTree";

interface NoteTreeListProps {
  nodes: TreeNode[];
  duplicateTitles: Set<string>;
  collapsedFolders: Set<string>;
  onToggleFolder: (folderPath: string) => void;
}

export function NoteTreeList({
  nodes,
  duplicateTitles,
  collapsedFolders,
  onToggleFolder,
}: NoteTreeListProps) {
  return (
    <ul className="note-tree">
      {nodes.map((node) => {
        if (node.type === "folder") {
          const isCollapsed = collapsedFolders.has(node.folderPath);
          return (
            <li key={`folder:${node.folderPath}`}>
              <button
                type="button"
                className="note-folder"
                onClick={() => onToggleFolder(node.folderPath)}
                aria-expanded={!isCollapsed}
              >
                <span
                  className={isCollapsed ? "folder-caret" : "folder-caret is-expanded"}
                >
                  {"▸"}
                </span>
                {node.name}
              </button>
              {!isCollapsed && (
                <NoteTreeList
                  nodes={node.children}
                  duplicateTitles={duplicateTitles}
                  collapsedFolders={collapsedFolders}
                  onToggleFolder={onToggleFolder}
                />
              )}
            </li>
          );
        }

        const { note } = node;
        return (
          <li key={note.path}>
            <NavLink
              to={`/notes/${encodeNotePath(note.path)}`}
              title={note.path}
              className={({ isActive }) =>
                isActive ? "note-link is-active" : "note-link"
              }
            >
              <span className="note-title">{note.title}</span>
              {duplicateTitles.has(note.title) && (
                <span className="note-path-hint">{note.path}</span>
              )}
            </NavLink>
          </li>
        );
      })}
    </ul>
  );
}

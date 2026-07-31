import type { NoteMeta } from "../types/note";

export interface FolderNode {
  type: "folder";
  name: string;
  /** Full path of this folder from the vault root, e.g. "a/b". */
  folderPath: string;
  children: TreeNode[];
}

export interface NoteTreeLeaf {
  type: "note";
  note: NoteMeta;
}

export type TreeNode = FolderNode | NoteTreeLeaf;

function sortChildren(children: TreeNode[]): TreeNode[] {
  return [...children].sort((a, b) => {
    if (a.type !== b.type) {
      return a.type === "folder" ? -1 : 1;
    }
    const aLabel = a.type === "folder" ? a.name : a.note.title;
    const bLabel = b.type === "folder" ? b.name : b.note.title;
    return aLabel.localeCompare(bLabel);
  });
}

/** Group a flat note list into a folder tree, mirroring each note's path. */
export function buildNoteTree(notes: NoteMeta[]): TreeNode[] {
  const root: FolderNode = { type: "folder", name: "", folderPath: "", children: [] };

  for (const note of notes) {
    const segments = note.path.split("/");
    let current = root;

    for (let i = 0; i < segments.length - 1; i++) {
      const folderName = segments[i];
      const folderPath = segments.slice(0, i + 1).join("/");
      let child = current.children.find(
        (candidate): candidate is FolderNode =>
          candidate.type === "folder" && candidate.name === folderName,
      );
      if (!child) {
        child = { type: "folder", name: folderName, folderPath, children: [] };
        current.children.push(child);
      }
      current = child;
    }

    current.children.push({ type: "note", note });
  }

  function sortTree(node: FolderNode): void {
    node.children = sortChildren(node.children);
    for (const child of node.children) {
      if (child.type === "folder") {
        sortTree(child);
      }
    }
  }
  sortTree(root);

  return root.children;
}

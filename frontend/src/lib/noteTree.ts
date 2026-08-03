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

/** Split a vault-relative note path into its containing folder and filename. */
export function splitNotePath(path: string): { folder: string; filename: string } {
  const idx = path.lastIndexOf("/");
  if (idx === -1) {
    return { folder: "", filename: path };
  }
  return { folder: path.slice(0, idx), filename: path.slice(idx + 1) };
}

/** Inverse of `splitNotePath`. */
export function joinNotePath(folder: string, filename: string): string {
  return folder ? `${folder}/${filename}` : filename;
}

/** Every folder path that appears anywhere in the vault, including
 * ancestors of nested folders (e.g. "a/b/c.md" contributes both "a" and
 * "a/b"). Sorted for stable rendering. */
export function collectFolderPaths(notes: NoteMeta[]): string[] {
  const folders = new Set<string>();
  for (const note of notes) {
    const segments = note.path.split("/");
    for (let i = 1; i < segments.length; i++) {
      folders.add(segments.slice(0, i).join("/"));
    }
  }
  return [...folders].sort();
}

/** The direct child folder names of `parent` (top-level names only, not
 * full paths), given the full set of folder paths in the vault. */
export function childFolderNames(allFolders: string[], parent: string): string[] {
  const prefix = parent ? `${parent}/` : "";
  const names = new Set<string>();
  for (const folder of allFolders) {
    if (parent && folder === parent) continue;
    if (!folder.startsWith(prefix)) continue;
    const rest = folder.slice(prefix.length);
    if (!rest) continue;
    names.add(rest.split("/")[0]);
  }
  return [...names].sort();
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

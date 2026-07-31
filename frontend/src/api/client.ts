import type { GraphResponse, Note, NoteMeta } from "../types/note";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}/api${path}`, init);
  if (!response.ok) {
    throw new Error(`${init?.method ?? "GET"} ${path} failed: ${response.status}`);
  }
  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function encodeNotePath(path: string): string {
  return path.split("/").map(encodeURIComponent).join("/");
}

export function listNotes(): Promise<NoteMeta[]> {
  return request<NoteMeta[]>("/notes");
}

export function getNote(path: string): Promise<Note> {
  return request<Note>(`/notes/${encodeNotePath(path)}`);
}

export function putNote(path: string, content: string): Promise<Note> {
  return request<Note>(`/notes/${encodeNotePath(path)}`, {
    method: "PUT",
    headers: { "Content-Type": "text/markdown" },
    body: content,
  });
}

export function deleteNote(path: string): Promise<void> {
  return request<void>(`/notes/${encodeNotePath(path)}`, { method: "DELETE" });
}

export function getGraph(): Promise<GraphResponse> {
  return request<GraphResponse>("/graph");
}

export function getBacklinks(path: string): Promise<NoteMeta[]> {
  return request<NoteMeta[]>(`/notes/${encodeNotePath(path)}/backlinks`);
}

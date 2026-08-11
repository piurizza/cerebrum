import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { encodeNotePath, errorMessage, getTasks } from "../api/client";
import type { TaskItem } from "../types/note";

interface TaskGroup {
  path: string;
  title: string;
  tasks: TaskItem[];
}

export function TasksPage() {
  const [tasks, setTasks] = useState<TaskItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getTasks()
      .then((result) => {
        setTasks(result);
        setError(null);
      })
      .catch((err: unknown) => setError(errorMessage(err)));
  }, []);

  // Partitions the flat response into per-note buckets -- it doesn't
  // re-sort. GET /tasks already orders by note path then line, and
  // Map insertion order preserves that both across groups and within
  // each group's own task list.
  const groups = useMemo<TaskGroup[]>(() => {
    if (!tasks) return [];
    const byPath = new Map<string, TaskGroup>();
    for (const task of tasks) {
      let group = byPath.get(task.path);
      if (!group) {
        group = { path: task.path, title: task.title, tasks: [] };
        byPath.set(task.path, group);
      }
      group.tasks.push(task);
    }
    return [...byPath.values()];
  }, [tasks]);

  // Titles aren't unique -- two notes in different folders can share a
  // title. Only show the disambiguating path for titles that actually
  // collide, so the common case (unique titles) stays uncluttered.
  // Mirrors NoteBrowser's identical duplicateTitles pattern.
  const duplicateTitles = useMemo(() => {
    const counts = new Map<string, number>();
    for (const group of groups) {
      counts.set(group.title, (counts.get(group.title) ?? 0) + 1);
    }
    return new Set(
      [...counts.entries()].filter(([, count]) => count > 1).map(([title]) => title),
    );
  }, [groups]);

  return (
    <div className="tasks-page">
      <h1>Tasks</h1>
      {error && (
        <p className="error-text" role="alert">
          Failed to load tasks: {error}
        </p>
      )}
      {!error && tasks === null && <p className="loading-indicator">Loading...</p>}
      {!error && tasks !== null && groups.length === 0 && (
        <p className="empty-hint">No open tasks.</p>
      )}
      {!error &&
        groups.map((group) => (
          <section key={group.path} className="task-group">
            <h2 className="task-group-title">
              <Link to={`/notes/${encodeNotePath(group.path)}`}>{group.title}</Link>
              {duplicateTitles.has(group.title) && (
                <span className="task-group-path"> ({group.path})</span>
              )}
            </h2>
            <ul className="task-list">
              {group.tasks.map((task) => (
                <li key={task.line}>
                  <Link to={`/notes/${encodeNotePath(group.path)}`}>{task.text}</Link>
                </li>
              ))}
            </ul>
          </section>
        ))}
    </div>
  );
}

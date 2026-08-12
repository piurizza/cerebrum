/** Titles aren't unique across a note collection -- two notes in
 * different folders can share a title, and (for `TasksPage`) two task
 * groups can too. Returns the set of titles that occur more than once,
 * so a caller can show a disambiguating detail (e.g. path) only for
 * colliding titles, keeping the common case (unique titles) uncluttered.
 * Shared by `NoteBrowser` and `TasksPage`, which both need this exact
 * computation over different item shapes. */
export function findDuplicateTitles<T>(
  items: T[],
  getTitle: (item: T) => string,
): Set<string> {
  const counts = new Map<string, number>();
  for (const item of items) {
    const title = getTitle(item);
    counts.set(title, (counts.get(title) ?? 0) + 1);
  }
  return new Set(
    [...counts.entries()].filter(([, count]) => count > 1).map(([title]) => title),
  );
}

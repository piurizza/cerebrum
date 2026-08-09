import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { NoteMeta } from "../../types/note";

const mockGetBacklinks = vi.fn<(path: string) => Promise<NoteMeta[]>>();
vi.mock("../../api/client", () => ({
  getBacklinks: (path: string) => mockGetBacklinks(path),
  encodeNotePath: (path: string) => path.split("/").map(encodeURIComponent).join("/"),
}));

// Importing after the mocks above are registered, matching how vi.mock's
// hoisting requires them to be declared -- import placement doesn't matter
// for the hoisted calls themselves, but keeping the subject-under-test
// import last documents the dependency order for readers.
import { BacklinksPanel } from "./BacklinksPanel";

const backlinks: NoteMeta[] = [
  { path: "notes/a.md", title: "Note A", tags: [], created: null, updated: null },
  { path: "notes/b.md", title: "Note B", tags: [], created: null, updated: null },
];

beforeEach(() => {
  mockGetBacklinks.mockReset();
});

afterEach(() => {
  vi.clearAllMocks();
});

describe("BacklinksPanel", () => {
  it("renders the empty-state hint when there are no backlinks", async () => {
    mockGetBacklinks.mockResolvedValue([]);

    render(
      <MemoryRouter>
        <BacklinksPanel path="notes/current.md" />
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(mockGetBacklinks).toHaveBeenCalledWith("notes/current.md"),
    );
    expect(await screen.findByText("No backlinks yet.")).toBeInTheDocument();
  });

  it("renders a linked list item per backlink with its title as visible text", async () => {
    mockGetBacklinks.mockResolvedValue(backlinks);

    render(
      <MemoryRouter>
        <BacklinksPanel path="notes/current.md" />
      </MemoryRouter>,
    );

    const linkA = await screen.findByRole("link", { name: "Note A" });
    expect(linkA).toHaveAttribute("href", "/notes/notes/a.md");

    const linkB = screen.getByRole("link", { name: "Note B" });
    expect(linkB).toHaveAttribute("href", "/notes/notes/b.md");
  });

  it("re-fetches backlinks when the path prop changes", async () => {
    mockGetBacklinks.mockResolvedValue([]);

    const { rerender } = render(
      <MemoryRouter>
        <BacklinksPanel path="notes/first.md" />
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(mockGetBacklinks).toHaveBeenCalledWith("notes/first.md"),
    );

    rerender(
      <MemoryRouter>
        <BacklinksPanel path="notes/second.md" />
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(mockGetBacklinks).toHaveBeenCalledWith("notes/second.md"),
    );
    expect(mockGetBacklinks).toHaveBeenCalledTimes(2);
  });
});

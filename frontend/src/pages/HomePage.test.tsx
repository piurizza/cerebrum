import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TagSearchBox } from "../components/NoteBrowser/TagSearchBox";
import { TagSelectionProvider, useTagSelection } from "../context/TagSelectionContext";
import { collectTagCounts } from "../lib/tagQuery";
import { makeNoteMeta } from "../test/factories";
import type { NoteMeta } from "../types/note";

const mockUseNotes =
  vi.fn<() => { notes: NoteMeta[]; error: string | null; loading: boolean }>();
vi.mock("../context/NotesContext", () => ({
  useNotes: () => mockUseNotes(),
}));

const mockSearchNotes = vi.fn();
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, searchNotes: (query: string) => mockSearchNotes(query) };
});

import { HomePage } from "./HomePage";

function note(path: string, tags: string[], updated: string | null = null): NoteMeta {
  return { ...makeNoteMeta(path, path.replace(/\.md$/, "")), tags, updated };
}

const NOTES = [
  note("work/plan.md", ["work"], "2026-10-20T10:00:00+00:00"),
  note("work/acme.md", ["Work/acme", "draft"], "2026-10-22"),
  note("home/garden.md", ["home"], "2026-10-21T09:00:00+02:00"),
  note("home/both.md", ["home", "work"], null),
];

function setNotes(
  notes: NoteMeta[],
  overrides: { error?: string | null; loading?: boolean } = {},
) {
  mockUseNotes.mockReturnValue({
    notes,
    error: overrides.error ?? null,
    loading: overrides.loading ?? false,
  });
}

function setViewport(isMobile: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: isMobile && query.includes("max-width: 768px"),
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(() => false),
  })) as unknown as typeof window.matchMedia;
}

// The sidebar search box beside the page, sharing one selection, plus a
// note route to navigate away and back.
function SidebarBox() {
  const { chips } = useTagSelection();
  return (
    <TagSearchBox
      counts={collectTagCounts(mockUseNotes().notes, chips)}
      onQueryTextChange={() => {}}
    />
  );
}

function renderHome() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <TagSelectionProvider>
        <SidebarBox />
        <Link to="/">home link</Link>
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/notes/*" element={<p>note page</p>} />
        </Routes>
      </TagSelectionProvider>
    </MemoryRouter>,
  );
}

const tag = (name: RegExp) => screen.getByRole("button", { name });
const resultTitles = () =>
  within(screen.getByRole("region", { name: "Matching notes" }))
    .getAllByRole("link")
    .map((link) => link.querySelector(".tag-result-title")?.textContent);

beforeEach(() => {
  setViewport(false);
  setNotes(NOTES);
  mockSearchNotes.mockReset();
});

describe("HomePage tag index", () => {
  it("lists every tag with its count, adding parents of nested tags", () => {
    renderHome();
    expect(tag(/^work \(3 notes\)$/)).toBeInTheDocument();
    expect(tag(/^Work\/acme \(1 note\)$/)).toHaveTextContent("acme 1");
    expect(tag(/^home \(2 notes\)$/)).toBeInTheDocument();
    expect(tag(/^draft/)).toBeInTheDocument();
  });

  it("narrows the index with the filter, keeping a matching child's parent", async () => {
    const user = userEvent.setup();
    renderHome();
    await user.type(screen.getByRole("searchbox", { name: "Filter tags" }), "acm");
    const index = screen.getByRole("region", { name: "All tags" });
    expect(
      within(index)
        .getAllByRole("button")
        .map((b) => b.getAttribute("aria-label")),
    ).toEqual(["work (3 notes)", "Work/acme (1 note)"]);
  });

  it("shows the notes matching a tapped tag, newest first", async () => {
    const user = userEvent.setup();
    renderHome();
    await user.click(tag(/^work \(/));

    expect(tag(/^work \(/)).toHaveAttribute("aria-pressed", "true");
    // 2026-10-22 (date only) > 2026-10-20T10:00Z; no date sorts last.
    expect(resultTitles()).toEqual(["work/acme", "work/plan", "home/both"]);
  });

  it("orders by the parsed date across offsets", async () => {
    setNotes([
      note("a.md", ["t"], "2026-10-21T01:00:00+02:00"), // 2026-10-20T23:00Z
      note("b.md", ["t"], "2026-10-20T23:30:00+00:00"),
    ]);
    const user = userEvent.setup();
    renderHome();
    await user.click(tag(/^t \(/));
    expect(resultTitles()).toEqual(["b", "a"]);
  });

  it("needs every tapped tag, and disables tags that would give nothing", async () => {
    const user = userEvent.setup();
    renderHome();
    await user.click(tag(/^home \(/));

    expect(tag(/^draft/)).toBeDisabled();
    await user.click(tag(/^work \(1 note\)/));
    expect(resultTitles()).toEqual(["home/both"]);
  });

  it("shares the selection with the sidebar search box", async () => {
    const user = userEvent.setup();
    renderHome();
    await user.click(tag(/^home \(/));
    expect(screen.getAllByRole("button", { name: "Remove tag home" })).toHaveLength(2);

    await user.type(screen.getByRole("combobox"), "-#draft ");
    expect(tag(/^Work\/acme/)).toBeDisabled();
    expect(
      screen.getAllByRole("button", { name: "Remove excluded tag draft" }),
    ).toHaveLength(2);
  });

  it("removes an exclusion from the selected bar, and a tap turns it into an include", async () => {
    const user = userEvent.setup();
    renderHome();
    await user.type(screen.getByRole("combobox"), "-#draft ");
    await user.click(tag(/^draft/));
    expect(tag(/^draft/)).toHaveAttribute("aria-pressed", "true");
    expect(resultTitles()).toEqual(["work/acme"]);

    const bar = screen.getAllByRole("button", { name: "Remove tag draft" });
    await user.click(bar[bar.length - 1]);
    expect(screen.queryByRole("region", { name: "Matching notes" })).toBeNull();
  });

  it("keeps the selection after opening a note and coming back", async () => {
    const user = userEvent.setup();
    renderHome();
    await user.click(tag(/^home \(/));
    await user.click(screen.getByRole("link", { name: /home\/garden/ }));
    expect(screen.getByText("note page")).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "home link" }));
    expect(tag(/^home \(/)).toHaveAttribute("aria-pressed", "true");
    expect(resultTitles()).toEqual(["home/garden", "home/both"]);
  });

  it("never asks the server", async () => {
    const user = userEvent.setup();
    renderHome();
    await user.click(tag(/^work \(/));
    expect(mockSearchNotes).not.toHaveBeenCalled();
  });
});

describe("HomePage on a phone", () => {
  beforeEach(() => setViewport(true));

  it("collapses the index on the first pick and focuses the toggle", async () => {
    const user = userEvent.setup();
    renderHome();
    await user.click(tag(/^work \(/));

    const toggle = screen.getByRole("button", { name: /Show all tags/ });
    expect(toggle).toHaveFocus();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("region", { name: "All tags" })).toBeNull();
    expect(resultTitles()).toHaveLength(3);
  });

  it("keeps the index open for more picks once reopened", async () => {
    const user = userEvent.setup();
    renderHome();
    await user.click(tag(/^work \(/));
    await user.click(screen.getByRole("button", { name: /Show all tags/ }));
    await user.click(tag(/^home \(/));

    expect(screen.getByRole("region", { name: "All tags" })).toBeInTheDocument();
    expect(resultTitles()).toEqual(["home/both"]);
    await user.click(screen.getByRole("button", { name: "Hide tags" }));
    expect(screen.queryByRole("region", { name: "All tags" })).toBeNull();
  });

  it("points to the menu for the search box", () => {
    renderHome();
    expect(screen.getByText(/open the menu and type #/)).toBeInTheDocument();
  });
});

describe("HomePage states", () => {
  it("shows a load error instead of an empty vault", () => {
    setNotes([], { error: "Network down" });
    renderHome();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Failed to load notes: Network down",
    );
    expect(screen.queryByText("No notes yet.")).toBeNull();
  });

  it("says when the vault is empty", () => {
    setNotes([]);
    renderHome();
    expect(screen.getByText("No notes yet.")).toBeInTheDocument();
  });

  it("explains how to add tags when no note has one", () => {
    setNotes([note("a.md", [])]);
    renderHome();
    expect(screen.getByText(/No tags yet/)).toBeInTheDocument();
  });

  it("shows the loading indicator while notes load", () => {
    setNotes([], { loading: true });
    renderHome();
    expect(screen.getByText("Loading notes...")).toBeInTheDocument();
  });
});

import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { TaskItem } from "../types/note";

const mockGetTasks = vi.fn<() => Promise<TaskItem[]>>();
// `encodeNotePath`/`errorMessage` are real logic worth exercising as-is
// (matches BacklinksPanel.test.tsx's pattern) -- only `getTasks` touches
// the network and needs mocking.
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return { ...actual, getTasks: () => mockGetTasks() };
});

import { TasksPage } from "./TasksPage";

function renderPage() {
  return render(
    <MemoryRouter>
      <TasksPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  mockGetTasks.mockReset();
});

describe("TasksPage", () => {
  it("renders the page-level Tasks heading", () => {
    mockGetTasks.mockResolvedValue([]);

    renderPage();

    expect(
      screen.getByRole("heading", { name: "Tasks", level: 1 }),
    ).toBeInTheDocument();
  });

  it("renders a loading indicator while getTasks() is in flight", () => {
    mockGetTasks.mockReturnValue(new Promise(() => {}));

    renderPage();

    expect(screen.getByText("Loading...")).toBeInTheDocument();
  });

  it("renders tasks grouped under their note's title heading, as plain text", async () => {
    mockGetTasks.mockResolvedValue([
      { path: "a.md", title: "Groceries", line: 1, text: "**Buy** milk" },
      { path: "a.md", title: "Groceries", line: 3, text: "Buy eggs" },
    ]);

    renderPage();

    expect(
      await screen.findByRole("heading", { name: "Groceries" }),
    ).toBeInTheDocument();
    // Rendered as literal text, not parsed as markdown -- react's default
    // text-node escaping means "**Buy**" never becomes bold.
    expect(screen.getByText("**Buy** milk")).toBeInTheDocument();
    expect(screen.getByText("Buy eggs")).toBeInTheDocument();
  });

  it("links a task and its note heading to the note", async () => {
    mockGetTasks.mockResolvedValue([
      { path: "folder/a.md", title: "Groceries", line: 1, text: "Buy milk" },
    ]);

    renderPage();

    const heading = await screen.findByRole("link", { name: "Groceries" });
    expect(heading).toHaveAttribute("href", "/notes/folder/a.md");

    const task = screen.getByRole("link", { name: "Buy milk" });
    expect(task).toHaveAttribute("href", "/notes/folder/a.md");
  });

  it('renders "No open tasks." when getTasks() resolves empty', async () => {
    mockGetTasks.mockResolvedValue([]);

    renderPage();

    expect(await screen.findByText("No open tasks.")).toBeInTheDocument();
  });

  it("renders a visible error message when getTasks() rejects", async () => {
    mockGetTasks.mockRejectedValue(new Error("network error"));

    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("network error");
  });

  it("groups tasks with identical text under their own separate note headings", async () => {
    mockGetTasks.mockResolvedValue([
      { path: "a.md", title: "Note A", line: 1, text: "Same task" },
      { path: "b.md", title: "Note B", line: 1, text: "Same task" },
    ]);

    renderPage();

    expect(await screen.findByRole("heading", { name: "Note A" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Note B" })).toBeInTheDocument();
    expect(screen.getAllByText("Same task")).toHaveLength(2);
  });

  it("disambiguates two notes that share the same title by showing their path", async () => {
    mockGetTasks.mockResolvedValue([
      { path: "work/plan.md", title: "Plan", line: 1, text: "Task one" },
      { path: "personal/plan.md", title: "Plan", line: 1, text: "Task two" },
    ]);

    renderPage();

    await waitFor(() => expect(mockGetTasks).toHaveBeenCalled());
    expect(screen.getByText("(work/plan.md)")).toBeInTheDocument();
    expect(screen.getByText("(personal/plan.md)")).toBeInTheDocument();
  });
});

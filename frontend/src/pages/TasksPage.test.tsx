import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api/client";
import { TagSelectionProvider, useTagSelection } from "../context/TagSelectionContext";
import { getDailyNoteHeading } from "../lib/dailyNote";
import { TASK_CHANGED_MESSAGE } from "../lib/tasks";
import { setCachedVaultReadOnly } from "../test/factories";
import type {
  AddTaskRequest,
  Note,
  SetTaskDoneRequest,
  TaskItem,
  TaskWriteResult,
} from "../types/note";

const mockGetTasks = vi.fn<() => Promise<TaskItem[]>>();
const mockGetDoneTasks = vi.fn<(since: string) => Promise<TaskItem[]>>();
const mockAddTask = vi.fn<(body: AddTaskRequest) => Promise<TaskWriteResult>>();
const mockSetTaskDone = vi.fn<(body: SetTaskDoneRequest) => Promise<TaskWriteResult>>();
// `encodeNotePath`/`errorMessage`/`ApiError` are real logic worth
// exercising as-is (matches BacklinksPanel.test.tsx's pattern) -- only the
// calls that touch the network are mocked.
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    getTasks: () => mockGetTasks(),
    getDoneTasks: (since: string) => mockGetDoneTasks(since),
    addTask: (body: AddTaskRequest) => mockAddTask(body),
    setTaskDone: (body: SetTaskDoneRequest) => mockSetTaskDone(body),
  };
});

const mockUseOffline =
  vi.fn<() => { isOffline: boolean; lastSyncedAt: string | null }>();
vi.mock("../context/OfflineContext", () => ({
  useOffline: () => mockUseOffline(),
}));

// Wikilinks resolve against no notes; an add refreshes the sidebar's list.
const mockRefreshNotes = vi.fn<() => Promise<void>>();
vi.mock("../context/NotesContext", () => ({
  useNotesIfLoaded: () => [],
  useRefreshNotesIfLoaded: () => mockRefreshNotes,
}));

import { TasksPage } from "./TasksPage";

const TODAY = new Date(2026, 9, 26, 10, 0);

function task(path: string, line: number, text: string, extra: Partial<TaskItem> = {}) {
  return {
    path,
    title: path.replace(/^.*\//, "").replace(/\.md$/, ""),
    line,
    text,
    tags: [],
    done: false,
    done_date: null,
    ...extra,
  } satisfies TaskItem;
}

function written(result: TaskItem): TaskWriteResult {
  return { note: { path: result.path } as Note, task: result };
}

// Picks a tag the way the front page or the sidebar search box would:
// through the one shared selection.
function PickTag({ tag }: { tag: string }) {
  const { addChip } = useTagSelection();
  return (
    <button type="button" onClick={() => addChip(tag, false)}>
      pick {tag}
    </button>
  );
}

function renderPage() {
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  const view = render(
    <MemoryRouter>
      <TagSelectionProvider>
        <PickTag tag="garden" />
        <TasksPage />
      </TagSelectionProvider>
    </MemoryRouter>,
  );
  return { user, ...view };
}

// The text of each row in the tab shown, in order.
function shownRows() {
  return within(screen.getByRole("tabpanel"))
    .queryAllByRole("listitem")
    .map((row) => row.querySelector(".task-row-text")?.textContent);
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true, now: TODAY });
  mockGetTasks.mockReset();
  mockGetDoneTasks.mockReset();
  mockGetDoneTasks.mockResolvedValue([]);
  mockAddTask.mockReset();
  mockSetTaskDone.mockReset();
  mockRefreshNotes.mockReset();
  mockRefreshNotes.mockResolvedValue(undefined);
  mockUseOffline.mockReturnValue({ isOffline: false, lastSyncedAt: null });
  // Never fetched: counts as writable.
  setCachedVaultReadOnly(null);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("TasksPage lists", () => {
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

  it("groups tasks under their note's title and renders their text as inline markdown", async () => {
    mockGetTasks.mockResolvedValue([
      task("a.md", 1, "**Buy** milk", { title: "Groceries" }),
      task("a.md", 3, "Buy `eggs`", { title: "Groceries" }),
    ]);

    renderPage();

    expect(
      await screen.findByRole("heading", { name: "Groceries" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Buy", { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByText("eggs").tagName).toBe("CODE");
    expect(screen.queryByText(/\*\*/)).toBeNull();
  });

  it("links the note heading to the note and each task to its line", async () => {
    mockGetTasks.mockResolvedValue([
      task("folder/a.md", 4, "Buy milk", { title: "Groceries" }),
    ]);

    renderPage();

    const heading = await screen.findByRole("link", { name: "Groceries" });
    expect(heading).toHaveAttribute("href", "/notes/folder/a.md");
    expect(screen.getByRole("link", { name: "Open" })).toHaveAttribute(
      "href",
      "/notes/folder/a.md?line=4",
    );
  });

  it("gives every open task a keyboard-reachable checkbox named by its text", async () => {
    mockGetTasks.mockResolvedValue([task("a.md", 1, "Call the *plumber*")]);
    const { user } = renderPage();

    const checkbox = await screen.findByRole("checkbox", { name: "Call the plumber" });
    expect(checkbox).not.toBeChecked();
    for (let i = 0; i < 15 && document.activeElement !== checkbox; i++) {
      await user.tab();
    }
    expect(checkbox).toHaveFocus();
  });

  it("says the vault has no open tasks when the list is empty", async () => {
    mockGetTasks.mockResolvedValue([]);

    renderPage();

    expect(await screen.findByText("No open tasks in the vault.")).toBeInTheDocument();
  });

  it("renders a visible error message when getTasks() rejects", async () => {
    mockGetTasks.mockRejectedValue(new Error("network error"));

    renderPage();

    expect(await screen.findByRole("alert")).toHaveTextContent("network error");
  });

  it("groups tasks with identical text under their own separate note headings", async () => {
    mockGetTasks.mockResolvedValue([
      task("a.md", 1, "Same task", { title: "Note A" }),
      task("b.md", 1, "Same task", { title: "Note B" }),
    ]);

    renderPage();

    expect(await screen.findByRole("heading", { name: "Note A" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Note B" })).toBeInTheDocument();
    expect(screen.getAllByText("Same task")).toHaveLength(2);
  });

  it("disambiguates two notes that share the same title by showing their path", async () => {
    mockGetTasks.mockResolvedValue([
      task("work/plan.md", 1, "Task one", { title: "Plan" }),
      task("personal/plan.md", 1, "Task two", { title: "Plan" }),
    ]);

    renderPage();

    expect(await screen.findByText("(work/plan.md)")).toBeInTheDocument();
    expect(screen.getByText("(personal/plan.md)")).toBeInTheDocument();
  });

  it("refetches when the window regains focus or becomes visible again", async () => {
    mockGetTasks.mockResolvedValue([task("a.md", 1, "Rake the leaves")]);
    renderPage();
    await screen.findByText("Rake the leaves");
    expect(mockGetTasks).toHaveBeenCalledTimes(1);

    mockGetTasks.mockResolvedValue([
      task("a.md", 1, "Rake the leaves"),
      task("b.md", 1, "Added on the phone"),
    ]);
    fireEvent.focus(window);
    expect(await screen.findByText("Added on the phone")).toBeInTheDocument();

    fireEvent(document, new Event("visibilitychange"));
    await waitFor(() => expect(mockGetTasks).toHaveBeenCalledTimes(3));
  });
});

describe("TasksPage adding", () => {
  it("adds to today's daily note with the Today button's heading, at once, keeping focus (AE1)", async () => {
    const timber = task("daily/2026-10-26.md", 3, "Order timber for the shed");
    mockGetTasks.mockResolvedValue([]);
    mockAddTask.mockResolvedValue(written(timber));
    const { user } = renderPage();
    await screen.findByText("No open tasks in the vault.");

    // The refetch after the add hasn't answered yet.
    let answer: (tasks: TaskItem[]) => void = () => {};
    mockGetTasks.mockReturnValue(
      new Promise((resolve) => {
        answer = resolve;
      }),
    );
    const input = screen.getByRole("textbox", { name: "New task" });
    await user.type(input, "Order timber for the shed{Enter}");

    expect(mockAddTask).toHaveBeenCalledWith({
      text: "Order timber for the shed",
      date: "2026-10-26",
      heading: getDailyNoteHeading(TODAY),
    });
    expect(await screen.findByText("Order timber for the shed")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "2026-10-26" })).toBeInTheDocument();
    expect(input).toHaveValue("");
    expect(input).toHaveFocus();
    expect(mockGetTasks).toHaveBeenCalledTimes(2);

    await act(async () => answer([timber]));
    expect(screen.getByText("Order timber for the shed")).toBeInTheDocument();
    expect(mockRefreshNotes).toHaveBeenCalled();
  });

  it("drops an added task once a refetch no longer lists it as open", async () => {
    const timber = task("daily/2026-10-26.md", 3, "Order timber for the shed");
    mockGetTasks.mockResolvedValue([]);
    mockAddTask.mockResolvedValue(written(timber));
    const { user } = renderPage();
    await screen.findByText("No open tasks in the vault.");

    mockGetTasks.mockResolvedValue([timber]);
    await user.type(
      screen.getByRole("textbox", { name: "New task" }),
      "Order timber for the shed{Enter}",
    );
    await waitFor(() => expect(mockGetTasks).toHaveBeenCalledTimes(2));
    expect(screen.getByText("Order timber for the shed")).toBeInTheDocument();

    // Ticked on another device since.
    mockGetTasks.mockResolvedValue([]);
    fireEvent.focus(window);

    expect(await screen.findByText("No open tasks in the vault.")).toBeInTheDocument();
    expect(screen.queryByText("Order timber for the shed")).toBeNull();
  });

  it("shows a task added outside the tag selection, marked as such (AE9)", async () => {
    mockGetTasks.mockResolvedValue([
      task("garden.md", 1, "Water the herbs", { tags: ["garden"] }),
      task("work.md", 1, "File the report", { tags: ["work"] }),
    ]);
    const potatoes = task("daily/2026-10-26.md", 3, "Buy seed potatoes");
    mockAddTask.mockResolvedValue(written(potatoes));
    const { user } = renderPage();
    await screen.findByText("Water the herbs");
    await user.click(screen.getByRole("button", { name: "pick garden" }));
    expect(screen.queryByText("File the report")).toBeNull();

    mockGetTasks.mockResolvedValue([
      task("garden.md", 1, "Water the herbs", { tags: ["garden"] }),
      task("work.md", 1, "File the report", { tags: ["work"] }),
      potatoes,
    ]);

    await user.type(
      screen.getByRole("textbox", { name: "New task" }),
      "Buy seed potatoes{Enter}",
    );

    await waitFor(() => expect(mockGetTasks).toHaveBeenCalledTimes(2));
    // Still shown, and flagged, once the refetch lists it.
    const row = (await screen.findByText("Buy seed potatoes")).closest("li");
    expect(row).not.toBeNull();
    expect(
      within(row as HTMLElement).getByText("Outside the current filters"),
    ).toBeInTheDocument();
    expect(screen.queryByText("File the report")).toBeNull();
    // A task that matches carries no flag.
    expect(
      within(
        screen.getByText("Water the herbs").closest("li") as HTMLElement,
      ).queryByText("Outside the current filters"),
    ).toBeNull();
  });

  it("keeps the text and shows the error inline when the add fails", async () => {
    mockGetTasks.mockResolvedValue([]);
    mockAddTask.mockRejectedValue(new ApiError("A task needs some text", 422));
    const { user } = renderPage();
    await screen.findByText("No open tasks in the vault.");

    const input = screen.getByRole("textbox", { name: "New task" });
    await user.type(input, "Order timber{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The task wasn't added: A task needs some text",
    );
    expect(input).toHaveValue("Order timber");
    expect(screen.getByText("No open tasks in the vault.")).toBeInTheDocument();
  });
});

describe("TasksPage ticking", () => {
  const herbs = task("garden.md", 5, "Water the herbs");
  const herbsDone = { ...herbs, done: true, done_date: "2026-10-26" };

  it("strikes a ticked row with Undo, and Undo sends an untick", async () => {
    mockGetTasks.mockResolvedValue([herbs]);
    mockSetTaskDone.mockResolvedValueOnce(written(herbsDone));
    const { user } = renderPage();

    await user.click(await screen.findByRole("checkbox", { name: "Water the herbs" }));

    expect(mockSetTaskDone).toHaveBeenCalledWith({
      path: "garden.md",
      line: 5,
      text: "Water the herbs",
      done: true,
      date: "2026-10-26",
    });
    expect(screen.getByRole("checkbox", { name: "Water the herbs" })).toBeChecked();
    expect(screen.getByText("Water the herbs").closest("li")).toHaveClass("is-struck");

    mockSetTaskDone.mockResolvedValueOnce(written(herbs));
    await user.click(screen.getByRole("button", { name: "Undo" }));

    await waitFor(() =>
      expect(mockSetTaskDone).toHaveBeenLastCalledWith({
        path: "garden.md",
        line: 5,
        text: "Water the herbs",
        done: false,
        date: null,
      }),
    );
    expect(screen.getByRole("checkbox", { name: "Water the herbs" })).not.toBeChecked();
    expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();
    act(() => vi.advanceTimersByTime(6000));
    expect(screen.getByText("Water the herbs")).toBeInTheDocument();
  });

  it("drops a ticked row from the open list once its 5 seconds are up", async () => {
    mockGetTasks.mockResolvedValue([herbs]);
    mockSetTaskDone.mockResolvedValue(written(herbsDone));
    const { user } = renderPage();
    const checkbox = await screen.findByRole("checkbox", { name: "Water the herbs" });

    mockGetTasks.mockResolvedValue([]);
    await user.click(checkbox);
    await waitFor(() => expect(mockGetTasks).toHaveBeenCalledTimes(2));
    act(() => vi.advanceTimersByTime(4000));
    expect(screen.getByText("Water the herbs")).toBeInTheDocument();

    act(() => vi.advanceTimersByTime(1100));

    expect(shownRows()).toEqual([]);
    expect(screen.getByText("No open tasks in the vault.")).toBeInTheDocument();
  });

  it("keeps the struck row and its Undo through a focus refetch", async () => {
    mockGetTasks.mockResolvedValue([herbs]);
    mockSetTaskDone.mockResolvedValue(written(herbsDone));
    const { user } = renderPage();
    const checkbox = await screen.findByRole("checkbox", { name: "Water the herbs" });

    // The server no longer lists it as open once it is ticked.
    mockGetTasks.mockResolvedValue([]);
    await user.click(checkbox);
    await waitFor(() => expect(mockGetTasks).toHaveBeenCalledTimes(2));
    fireEvent.focus(window);
    await waitFor(() => expect(mockGetTasks).toHaveBeenCalledTimes(3));

    expect(screen.getByRole("checkbox", { name: "Water the herbs" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
  });

  it("puts a tick back, says the task changed and refetches on a 409 (AE4)", async () => {
    const plumber = task("house.md", 2, "Call the plumber");
    mockGetTasks.mockResolvedValue([plumber]);
    mockSetTaskDone.mockRejectedValue(
      new ApiError("The note changed since the task was loaded", 409),
    );
    const { user } = renderPage();
    const checkbox = await screen.findByRole("checkbox", { name: "Call the plumber" });

    mockGetTasks.mockResolvedValue([task("house.md", 2, "Call the electrician")]);
    await user.click(checkbox);

    expect(await screen.findByRole("alert")).toHaveTextContent(TASK_CHANGED_MESSAGE);
    expect(await screen.findByText("Call the electrician")).toBeInTheDocument();
    expect(screen.queryByText("Call the plumber")).toBeNull();
    expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();
  });

  it("puts a tick back with the same kind of message on any other failure", async () => {
    mockGetTasks.mockResolvedValue([herbs]);
    mockSetTaskDone.mockRejectedValue(new ApiError("Vault is read-only", 403));
    const { user } = renderPage();
    await user.click(await screen.findByRole("checkbox", { name: "Water the herbs" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The task wasn't ticked: Vault is read-only",
    );
    expect(screen.getByRole("checkbox", { name: "Water the herbs" })).not.toBeChecked();
    expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();
  });
});

describe("TasksPage Done tab", () => {
  const mockDoneSweep = () =>
    task("a.md", 1, "Sweep the path", { done: true, done_date: "2026-10-24" });

  it("lists the last 14 days by done date, newest first", async () => {
    mockGetTasks.mockResolvedValue([]);
    mockGetDoneTasks.mockResolvedValue([
      task("a.md", 1, "Rake the leaves", { done: true, done_date: "2026-10-26" }),
      task("b.md", 2, "Sweep the path", { done: true, done_date: "2026-10-25" }),
      task("c.md", 3, "Prune the roses", { done: true, done_date: "2026-10-20" }),
    ]);
    const { user } = renderPage();

    await user.click(screen.getByRole("tab", { name: "Done" }));

    expect(mockGetDoneTasks).toHaveBeenCalledWith("2026-10-13");
    const panel = screen.getByRole("tabpanel");
    await within(panel).findByText("Rake the leaves");
    const headings = within(panel)
      .getAllByRole("heading", { level: 2 })
      .map((heading) => heading.textContent);
    expect(headings).toEqual([
      "Today",
      "Yesterday",
      new Intl.DateTimeFormat(undefined, { dateStyle: "full" }).format(
        new Date(2026, 9, 20),
      ),
    ]);
    expect(screen.getByRole("checkbox", { name: "Rake the leaves" })).toBeChecked();
    // Each row says which note it is in.
    expect(within(panel).getByText("a")).toBeInTheDocument();
  });

  it("shows a task ticked on the open list at the top of the Done tab (AE2)", async () => {
    const herbs = task("garden.md", 5, "Water the herbs");
    mockGetTasks.mockResolvedValue([herbs]);
    mockGetDoneTasks.mockResolvedValue([mockDoneSweep()]);
    const herbsDone = { ...herbs, done: true, done_date: "2026-10-26" };
    mockSetTaskDone.mockResolvedValue(written(herbsDone));
    const { user } = renderPage();
    const checkbox = await screen.findByRole("checkbox", { name: "Water the herbs" });

    // The tick lands in the list before the refetch answers.
    let answer: (tasks: TaskItem[]) => void = () => {};
    mockGetDoneTasks.mockReturnValue(
      new Promise((resolve) => {
        answer = resolve;
      }),
    );
    await user.click(checkbox);
    await waitFor(() => expect(mockGetTasks).toHaveBeenCalledTimes(2));
    await user.click(screen.getByRole("tab", { name: "Done" }));

    expect(shownRows()).toEqual(["Water the herbs", "Sweep the path"]);
    expect(screen.getByRole("checkbox", { name: "Water the herbs" })).toBeChecked();

    await act(async () => answer([herbsDone, mockDoneSweep()]));
    expect(shownRows()).toEqual(["Water the herbs", "Sweep the path"]);
  });

  it("moves an unticked done task back to the open list (AE3)", async () => {
    const herbsDone = task("garden.md", 5, "Water the herbs", {
      done: true,
      done_date: "2026-10-26",
    });
    mockGetTasks.mockResolvedValue([]);
    mockGetDoneTasks.mockResolvedValue([herbsDone]);
    mockSetTaskDone.mockResolvedValue(
      written({ ...herbsDone, done: false, done_date: null }),
    );
    const { user } = renderPage();
    await user.click(screen.getByRole("tab", { name: "Done" }));
    const checkbox = await screen.findByRole("checkbox", { name: "Water the herbs" });

    mockGetTasks.mockResolvedValue([{ ...herbsDone, done: false, done_date: null }]);
    mockGetDoneTasks.mockResolvedValue([]);
    await user.click(checkbox);

    expect(mockSetTaskDone).toHaveBeenCalledWith({
      path: "garden.md",
      line: 5,
      text: "Water the herbs",
      done: false,
      date: null,
    });
    // Still shown, unticked, with Undo, until its 5 seconds are up.
    expect(screen.getByRole("checkbox", { name: "Water the herbs" })).not.toBeChecked();
    await waitFor(() => expect(mockGetTasks).toHaveBeenCalledTimes(2));
    act(() => vi.advanceTimersByTime(5100));
    expect(screen.getByText("Nothing ticked in the last 14 days.")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /Open/ }));
    expect(screen.getByRole("checkbox", { name: "Water the herbs" })).not.toBeChecked();
  });

  it("re-ticks an untick undone on the Done tab with its own done date", async () => {
    const sweptDone = task("a.md", 1, "Sweep the path", {
      done: true,
      done_date: "2026-10-20",
    });
    mockGetTasks.mockResolvedValue([]);
    mockGetDoneTasks.mockResolvedValue([sweptDone]);
    mockSetTaskDone.mockResolvedValueOnce(
      written({ ...sweptDone, done: false, done_date: null }),
    );
    mockSetTaskDone.mockResolvedValueOnce(written(sweptDone));
    const { user } = renderPage();
    await user.click(screen.getByRole("tab", { name: "Done" }));
    await user.click(await screen.findByRole("checkbox", { name: "Sweep the path" }));

    await user.click(screen.getByRole("button", { name: "Undo" }));

    await waitFor(() =>
      expect(mockSetTaskDone).toHaveBeenLastCalledWith({
        path: "a.md",
        line: 1,
        text: "Sweep the path",
        done: true,
        date: "2026-10-20",
      }),
    );
  });

  it("says nothing was ticked in the last 14 days", async () => {
    mockGetTasks.mockResolvedValue([task("a.md", 1, "Open one")]);
    const { user } = renderPage();

    await user.click(screen.getByRole("tab", { name: "Done" }));

    expect(
      await screen.findByText("Nothing ticked in the last 14 days."),
    ).toBeInTheDocument();
  });
});

describe("TasksPage filters", () => {
  const OPEN = [
    task("home/garden.md", 1, "Order timber for the shed", { tags: ["garden"] }),
    task("work/plan.md", 1, "File the report", { tags: ["work"] }),
    task("work/clients/acme.md", 2, "Send the acme invoice", { tags: ["work"] }),
  ];
  const DONE = [
    task("home/garden.md", 3, "Rake the leaves", {
      tags: ["garden"],
      done: true,
      done_date: "2026-10-26",
    }),
    task("work/clients/acme.md", 4, "Call acme", {
      tags: ["work"],
      done: true,
      done_date: "2026-10-25",
    }),
  ];

  beforeEach(() => {
    mockGetTasks.mockResolvedValue(OPEN);
    mockGetDoneTasks.mockResolvedValue(DONE);
  });

  it("filters by folder, subfolders included, on both tabs", async () => {
    const { user } = renderPage();
    await screen.findByText("File the report");

    const select = screen.getByRole("combobox", { name: "Folder" });
    expect(within(select).getByRole("option", { name: "work/clients" })).toBeVisible();
    await user.selectOptions(select, "work");

    expect(shownRows()).toEqual(["Send the acme invoice", "File the report"]);
    await user.click(screen.getByRole("tab", { name: "Done" }));
    expect(shownRows()).toEqual(["Call acme"]);
  });

  it("narrows by words as they are typed, on both tabs", async () => {
    const { user } = renderPage();
    await screen.findByText("File the report");

    const words = screen.getByRole("searchbox", { name: "Filter by words" });
    await user.type(words, "t");
    expect(shownRows()).toEqual([
      "Order timber for the shed",
      "Send the acme invoice",
      "File the report",
    ]);
    await user.type(words, "imber");
    expect(shownRows()).toEqual(["Order timber for the shed"]);

    await user.click(screen.getByRole("tab", { name: "Done" }));
    await user.clear(words);
    await user.type(words, "acme");
    expect(shownRows()).toEqual(["Call acme"]);
  });

  it("filters by the tag picked elsewhere, showing its chip with Clear (AE6)", async () => {
    const { user } = renderPage();
    await screen.findByText("File the report");

    await user.click(screen.getByRole("button", { name: "pick garden" }));

    expect(shownRows()).toEqual(["Order timber for the shed"]);
    expect(screen.getByText("#garden")).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "Done" }));
    expect(shownRows()).toEqual(["Rake the leaves"]);

    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect(shownRows()).toEqual(["Rake the leaves", "Call acme"]);
    expect(screen.queryByText("#garden")).toBeNull();
  });

  it("names the filters that leave nothing and clears them all", async () => {
    const { user } = renderPage();
    await screen.findByText("File the report");
    await user.click(screen.getByRole("button", { name: "pick garden" }));
    await user.selectOptions(screen.getByRole("combobox", { name: "Folder" }), "work");

    expect(
      screen.getByText("No open tasks match #garden, folder work."),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear filters" }));

    expect(shownRows()).toHaveLength(3);
    expect(screen.getByRole("combobox", { name: "Folder" })).toHaveValue("");
    expect(screen.queryByText("#garden")).toBeNull();
  });
});

describe("TasksPage write gating", () => {
  it("disables adding and ticking offline, still showing the last loaded tasks (AE8)", async () => {
    mockUseOffline.mockReturnValue({ isOffline: true, lastSyncedAt: null });
    mockGetTasks.mockResolvedValue([task("a.md", 1, "Water the herbs")]);

    renderPage();

    expect(
      await screen.findByRole("checkbox", { name: "Water the herbs" }),
    ).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "New task" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
  });

  it("hides adding and ticking on a read-only vault", async () => {
    setCachedVaultReadOnly(true);
    mockGetTasks.mockResolvedValue([task("a.md", 1, "Water the herbs")]);

    renderPage();

    expect(await screen.findByText("Water the herbs")).toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("textbox", { name: "New task" })).toBeNull();
  });
});

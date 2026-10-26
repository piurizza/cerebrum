import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MarkdownPreview, type TaskToggle } from "./MarkdownPreview";

// `fetchAttachmentBlobUrl` hits the network (via `fetchWithRetry`), which
// isn't available in jsdom -- mock it so `AttachmentImage` gets a
// controllable promise instead. `encodeNotePath` is real logic worth
// exercising as-is (it's a pure path-encoding helper), so it's re-exported
// from the actual module rather than mocked.
vi.mock("../../api/client", async () => {
  const actual =
    await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return {
    ...actual,
    fetchAttachmentBlobUrl: vi.fn(),
    findAttachment: vi.fn(),
  };
});

// The note list wikilinks resolve against -- the real hook needs a
// NotesProvider, which would fetch.
let notePaths: string[] = [];
vi.mock("../../context/NotesContext", async () => {
  const { NoteLookup } =
    await vi.importActual<typeof import("../../lib/wikilinks")>("../../lib/wikilinks");
  return { useNoteLookup: () => new NoteLookup(notePaths) };
});

vi.mock("../../lib/mermaid", () => ({ renderMermaid: vi.fn() }));

import { ApiError, fetchAttachmentBlobUrl, findAttachment } from "../../api/client";
import { ThemeProvider } from "../../context/ThemeContext";
import { renderMermaid } from "../../lib/mermaid";
import { frontmatterLineCount, stripFrontmatter } from "../../lib/noteContent";

const mockFetchAttachmentBlobUrl = vi.mocked(fetchAttachmentBlobUrl);
const mockFindAttachment = vi.mocked(findAttachment);
const mockRenderMermaid = vi.mocked(renderMermaid);

function renderPreview(body: string, currentPath = "notes/a.md") {
  return render(
    <MemoryRouter>
      <ThemeProvider>
        <MarkdownPreview body={body} currentPath={currentPath} />
      </ThemeProvider>
    </MemoryRouter>,
  );
}

describe("MarkdownPreview", () => {
  beforeEach(() => {
    mockFetchAttachmentBlobUrl.mockReset();
    mockFindAttachment.mockReset();
    mockRenderMermaid.mockReset();
    notePaths = [];
  });

  it("renders an internal .md link as a router Link to the resolved note path", () => {
    renderPreview("[see also](b.md)", "notes/a.md");

    const link = screen.getByRole("link", { name: "see also" });
    expect(link).toHaveAttribute("href", "/notes/notes/b.md");
  });

  it("links to a note whose name has spaces, written encoded or in angle brackets", () => {
    renderPreview("[encoded](My%20Note.md) and [angled](<My Note.md>)", "notes/a.md");

    for (const name of ["encoded", "angled"]) {
      expect(screen.getByRole("link", { name })).toHaveAttribute(
        "href",
        "/notes/notes/My%20Note.md",
      );
    }
  });

  it("renders an external link as a plain anchor with target=_blank and rel", () => {
    renderPreview("[example](https://example.com)");

    const link = screen.getByRole("link", { name: "example" });
    expect(link).toHaveAttribute("href", "https://example.com");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it("renders nothing until the attachment fetch resolves, then shows the image", async () => {
    let resolveFetch!: (url: string) => void;
    mockFetchAttachmentBlobUrl.mockReturnValue(
      new Promise<string>((resolve) => {
        resolveFetch = resolve;
      }),
    );

    renderPreview("![alt text](image.png)", "notes/a.md");

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(mockFetchAttachmentBlobUrl).toHaveBeenCalledWith("notes/image.png");

    resolveFetch("blob:mock-url");

    const img = await screen.findByRole("img", { name: "alt text" });
    expect(img).toHaveAttribute("src", "blob:mock-url");
  });

  it("shows the 'Image unavailable' fallback when the attachment fetch fails", async () => {
    mockFetchAttachmentBlobUrl.mockRejectedValue(new Error("boom"));

    renderPreview("![alt text](image.png)", "notes/a.md");

    await waitFor(() => {
      expect(screen.getByText("Image unavailable")).toBeInTheDocument();
    });
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("renders an external image src as a plain, unresolved <img>", () => {
    renderPreview("![alt text](https://example.com/pic.png)");

    const img = screen.getByRole("img", { name: "alt text" });
    expect(img).toHaveAttribute("src", "https://example.com/pic.png");
    expect(mockFetchAttachmentBlobUrl).not.toHaveBeenCalled();
  });

  describe("mermaid blocks", () => {
    const fence = "```";

    it("renders a fenced mermaid block as the diagram SVG", async () => {
      mockRenderMermaid.mockResolvedValue(
        '<svg data-testid="diagram"><text>A</text></svg>',
      );

      renderPreview(`${fence}mermaid\nflowchart LR\n  A --> B\n${fence}`);

      expect(await screen.findByTestId("diagram")).toBeInTheDocument();
      expect(screen.getByRole("img", { name: "Diagram" })).toBeInTheDocument();
      expect(mockRenderMermaid).toHaveBeenCalledWith(
        "flowchart LR\n  A --> B",
        "light",
      );
    });

    it("shows the parse error and keeps the source visible when rendering fails", async () => {
      mockRenderMermaid.mockRejectedValue(new Error("Parse error on line 2"));

      renderPreview(`${fence}mermaid\nflowchart LR\n  A --\n${fence}`);

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Parse error on line 2",
      );
      expect(screen.getByText(/flowchart LR/)).toBeInTheDocument();
    });

    it("leaves other fenced code blocks as plain code", () => {
      renderPreview(`${fence}sql\nSELECT 1;\n${fence}`);

      expect(screen.getByText("SELECT 1;").closest("pre")).not.toBeNull();
      expect(mockRenderMermaid).not.toHaveBeenCalled();
    });

    it("does not treat inline code mentioning mermaid as a diagram", () => {
      renderPreview("Use a `mermaid` block.");

      expect(screen.getByText("mermaid").tagName).toBe("CODE");
      expect(mockRenderMermaid).not.toHaveBeenCalled();
    });
  });

  describe("wikilinks", () => {
    it("links a wikilink to the note with that file name", () => {
      notePaths = ["notes/a.md", "people/B.md"];
      renderPreview("see [[b]]", "notes/a.md");

      const link = screen.getByRole("link", { name: "b" });
      expect(link).toHaveAttribute("href", "/notes/people/B.md");
    });

    it("shows the alias, or the target with its heading", () => {
      notePaths = ["notes/a.md", "B.md"];
      renderPreview("[[B|Bee]] and [[B#Part]]", "notes/a.md");

      expect(screen.getByRole("link", { name: "Bee" })).toHaveAttribute(
        "href",
        "/notes/B.md",
      );
      expect(screen.getByRole("link", { name: "B#Part" })).toHaveAttribute(
        "href",
        "/notes/B.md",
      );
    });

    it("links a heading-only wikilink to the current note", () => {
      notePaths = ["notes/a.md"];
      renderPreview("[[#Top]]", "notes/a.md");

      expect(screen.getByRole("link", { name: "#Top" })).toHaveAttribute(
        "href",
        "/notes/notes/a.md",
      );
    });

    it("renders a note embed as a link", () => {
      notePaths = ["notes/a.md", "B.md"];
      renderPreview("![[B]]", "notes/a.md");

      expect(screen.getByRole("link", { name: "B" })).toHaveAttribute(
        "href",
        "/notes/B.md",
      );
    });

    it("marks an unresolved wikilink without making it a link", () => {
      notePaths = ["notes/a.md"];
      const { container } = renderPreview("[[Missing]] and [[doc.pdf]]");

      expect(screen.queryByRole("link")).toBeNull();
      const marks = container.querySelectorAll(".markdown-preview__unresolved");
      expect([...marks].map((mark) => mark.textContent)).toEqual([
        "Missing",
        "doc.pdf",
      ]);
    });

    it("leaves wikilinks in code as code", () => {
      notePaths = ["B.md"];
      renderPreview("`[[B]]`\n\n```\n[[B]]\n```");

      expect(screen.queryByRole("link")).toBeNull();
      expect(screen.getAllByText("[[B]]")).toHaveLength(2);
    });

    it("finds and shows an embedded image by name", async () => {
      mockFindAttachment.mockResolvedValue({ path: "photos/cat.png" });
      mockFetchAttachmentBlobUrl.mockResolvedValue("blob:cat");
      renderPreview("![[cat.png|A cat]]", "notes/a.md");

      const image = await screen.findByRole("img", { name: "A cat" });
      expect(image).toHaveAttribute("src", "blob:cat");
      expect(mockFindAttachment).toHaveBeenCalledWith("cat.png", "notes/a.md");
      expect(mockFetchAttachmentBlobUrl).toHaveBeenCalledWith("photos/cat.png");
    });

    it("marks an embedded image that isn't in the vault", async () => {
      mockFindAttachment.mockRejectedValue(new ApiError("Attachment not found", 404));
      const { container } = renderPreview("![[gone.png]]");

      await waitFor(() =>
        expect(
          container.querySelector(".markdown-preview__unresolved")?.textContent,
        ).toBe("gone.png"),
      );
      expect(mockFetchAttachmentBlobUrl).not.toHaveBeenCalled();
    });
  });
});

interface TaskLineCases {
  extract: {
    name: string;
    content: string;
    tasks: { line: number; checked: boolean; text: string }[];
  }[];
}

// A path, not `new URL(..., import.meta.url)` as the node-environment
// tests use: under jsdom, `URL` is jsdom's own, which readFileSync refuses.
const taskLineCases = JSON.parse(
  readFileSync(
    resolve(import.meta.dirname, "../../../../fixtures/task-lines.json"),
    "utf-8",
  ),
) as TaskLineCases;

// The preview as NoteViewPage renders it: the body without its
// frontmatter, numbered back to file lines.
function renderNote(
  content: string,
  props: Partial<ComponentProps<typeof MarkdownPreview>> = {},
) {
  return render(
    <MemoryRouter>
      <ThemeProvider>
        <MarkdownPreview
          body={stripFrontmatter(content)}
          lineOffset={frontmatterLineCount(content)}
          currentPath="notes/a.md"
          {...props}
        />
      </ThemeProvider>
    </MemoryRouter>,
  );
}

function toggleFor(content: string, overrides: Partial<TaskToggle> = {}): TaskToggle {
  return { content, disabled: false, hint: null, onToggle: vi.fn(), ...overrides };
}

describe("MarkdownPreview task items", () => {
  const note =
    "---\ntitle: Garden\ntags: [home]\n---\n\n# Garden\n- [ ] Water the [[herbs]]\n- [x] Rake ✅ 2026-10-20\n";

  beforeEach(() => {
    notePaths = [];
  });

  it("marks each task item with its file line, frontmatter included", () => {
    const { container } = renderNote(note);

    const lines = [...container.querySelectorAll("li.task-list-item")].map((item) =>
      item.getAttribute("data-source-line"),
    );
    expect(lines).toEqual(["7", "8"]);
  });

  it("names each checkbox by its item's text", () => {
    renderNote(note);

    expect(screen.getByRole("checkbox", { name: "Water the herbs" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Rake ✅ 2026-10-20" })).toBeChecked();
  });

  it("leaves checkboxes disabled when no toggle is given (a read-only vault)", () => {
    renderNote(note);

    for (const box of screen.getAllByRole("checkbox")) expect(box).toBeDisabled();
  });

  it("sends the file line, the line's text and the new state on a click", () => {
    const tasks = toggleFor(note);
    renderNote(note, { tasks });

    fireEvent.click(screen.getByRole("checkbox", { name: "Water the herbs" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Rake ✅ 2026-10-20" }));

    expect(tasks.onToggle).toHaveBeenNthCalledWith(1, {
      line: 7,
      text: "Water the [[herbs]]",
      done: true,
    });
    expect(tasks.onToggle).toHaveBeenNthCalledWith(2, {
      line: 8,
      text: "Rake ✅ 2026-10-20",
      done: false,
    });
  });

  it("is keyboard-operable: Space on a focused checkbox toggles it", () => {
    const tasks = toggleFor(note);
    renderNote(note, { tasks });

    const box = screen.getByRole("checkbox", { name: "Water the herbs" });
    box.focus();
    expect(box).toHaveFocus();
    // jsdom turns a click into the change a Space keypress makes.
    fireEvent.click(box);
    expect(tasks.onToggle).toHaveBeenCalledTimes(1);
  });

  it("disables a task item whose file line doesn't hold the task pattern", () => {
    // GFM renders a checkbox in an ordered list; the file grammar doesn't.
    const content = "1. [ ] Numbered\n- [ ] Bulleted\n";
    renderNote(content, { tasks: toggleFor(content) });

    expect(screen.getByRole("checkbox", { name: "Numbered" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Bulleted" })).toBeEnabled();
  });

  it("disables every checkbox with the hint when told to", () => {
    renderNote(note, {
      tasks: toggleFor(note, {
        disabled: true,
        hint: "Save first to tick tasks here.",
      }),
    });

    const hint = screen.getByText("Save first to tick tasks here.");
    for (const box of screen.getAllByRole("checkbox")) {
      expect(box).toBeDisabled();
      expect(box).toHaveAccessibleDescription("Save first to tick tasks here.");
    }
    expect(hint).toBeVisible();
  });

  it("shows no hint on a note without tasks", () => {
    renderNote("Just text\n", {
      tasks: toggleFor("Just text\n", { disabled: true, hint: "Save first" }),
    });

    expect(screen.queryByText("Save first")).not.toBeInTheDocument();
  });

  it("names a nested item's checkbox by its own text only", () => {
    const content = "- [ ] Parent\n  - [ ] Child\n";
    const { container } = renderNote(content);

    expect(screen.getByRole("checkbox", { name: "Parent" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Child" })).toBeInTheDocument();
    const lines = [...container.querySelectorAll("li.task-list-item")].map((item) =>
      item.getAttribute("data-source-line"),
    );
    expect(lines).toEqual(["1", "2"]);
  });

  it("marks the highlighted line's item, with a text equivalent", () => {
    const { container } = renderNote(note, { highlightLine: 7 });

    const item = container.querySelector('[data-source-line="7"]');
    expect(item).toHaveClass("task-list-item--highlight");
    expect(item).toHaveTextContent("The task you opened");
    expect(container.querySelector('[data-source-line="8"]')).not.toHaveClass(
      "task-list-item--highlight",
    );
  });

  describe("shared task-line cases", () => {
    it.each(taskLineCases.extract.map((c) => [c.name, c] as const))(
      "numbers %s like the server",
      (_, c) => {
        const tasks = toggleFor(c.content);
        const { container } = renderNote(c.content, { tasks });

        const items = [...container.querySelectorAll("li.task-list-item")];
        expect(
          items.map((item) => ({
            line: Number(item.getAttribute("data-source-line")),
            checked: (item.querySelector("input") as HTMLInputElement).checked,
          })),
        ).toEqual(c.tasks.map(({ line, checked }) => ({ line, checked })));

        for (const item of items) {
          fireEvent.click(item.querySelector("input") as HTMLInputElement);
        }
        expect(vi.mocked(tasks.onToggle).mock.calls.map(([task]) => task)).toEqual(
          c.tasks.map(({ line, checked, text }) => ({ line, text, done: !checked })),
        );
      },
    );
  });
});

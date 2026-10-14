import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MarkdownPreview } from "./MarkdownPreview";

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
  };
});

vi.mock("../../lib/mermaid", () => ({ renderMermaid: vi.fn() }));

import { fetchAttachmentBlobUrl } from "../../api/client";
import { ThemeProvider } from "../../context/ThemeContext";
import { renderMermaid } from "../../lib/mermaid";

const mockFetchAttachmentBlobUrl = vi.mocked(fetchAttachmentBlobUrl);
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
    mockRenderMermaid.mockReset();
  });

  it("renders an internal .md link as a router Link to the resolved note path", () => {
    renderPreview("[see also](b.md)", "notes/a.md");

    const link = screen.getByRole("link", { name: "see also" });
    expect(link).toHaveAttribute("href", "/notes/notes/b.md");
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
});

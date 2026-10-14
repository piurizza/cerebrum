import DOMPurify from "dompurify";
import { beforeEach, describe, expect, it, vi } from "vitest";

// jsdom has no layout engine, so real mermaid cannot render here. Mock it
// and test what this module owns: sanitization, config, ordering, errors.
const mermaidApi = vi.hoisted(() => ({
  initialize: vi.fn(),
  parse: vi.fn(),
  render: vi.fn(),
}));
vi.mock("mermaid", () => ({ default: mermaidApi }));

import { renderMermaid, sanitizeSvg } from "./mermaid";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

beforeEach(() => {
  mermaidApi.initialize.mockReset();
  mermaidApi.parse.mockReset().mockResolvedValue({ diagramType: "flowchart" });
  mermaidApi.render
    .mockReset()
    .mockResolvedValue({ svg: "<svg><text>ok</text></svg>" });
});

describe("sanitizeSvg", () => {
  it("removes scripts, event handlers and javascript: links", () => {
    const dirty =
      '<svg><script>alert(1)</script><g onclick="alert(2)"><a href="javascript:alert(3)"><text>label</text></a></g></svg>';

    const clean = sanitizeSvg(DOMPurify, dirty);

    expect(clean).toContain("label");
    expect(clean).not.toContain("<script");
    expect(clean).not.toContain("onclick");
    expect(clean).not.toContain("javascript:");
  });

  it("removes HTML smuggled in through foreignObject", () => {
    const clean = sanitizeSvg(
      DOMPurify,
      '<svg><foreignObject><img src="x" onerror="alert(1)"></foreignObject><text>a</text></svg>',
    );

    expect(clean).not.toContain("onerror");
    expect(clean).not.toContain("<img");
  });

  it("keeps the style element mermaid relies on for colours and markers", () => {
    const clean = sanitizeSvg(
      DOMPurify,
      "<svg><style>.node{fill:#fff}</style><text>a</text></svg>",
    );

    expect(clean).toContain("<style>");
  });
});

describe("renderMermaid", () => {
  it("returns sanitized SVG from mermaid's render", async () => {
    mermaidApi.render.mockResolvedValue({
      svg: '<svg><g onclick="x()"><text>A</text></g></svg>',
    });

    const svg = await renderMermaid("flowchart LR\n A-->B", "light");

    expect(svg).toContain("A");
    expect(svg).not.toContain("onclick");
  });

  it("initializes with strict security, SVG labels and the matching theme", async () => {
    await renderMermaid("flowchart LR\n A-->B", "dark");

    expect(mermaidApi.initialize).toHaveBeenCalledWith(
      expect.objectContaining({
        securityLevel: "strict",
        htmlLabels: false,
        startOnLoad: false,
        theme: "dark",
      }),
    );
  });

  it("rejects with the parse error and never calls render for invalid source", async () => {
    mermaidApi.parse.mockRejectedValue(new Error("Parse error on line 1"));

    await expect(renderMermaid("not a diagram", "light")).rejects.toThrow(
      "Parse error on line 1",
    );
    expect(mermaidApi.render).not.toHaveBeenCalled();
  });

  it("runs renders one at a time so a theme never applies to another diagram", async () => {
    const first = deferred<{ svg: string }>();
    mermaidApi.render.mockReturnValueOnce(first.promise);
    mermaidApi.render.mockResolvedValueOnce({ svg: "<svg><text>second</text></svg>" });

    const firstRender = renderMermaid("flowchart LR\n A-->B", "light");
    const secondRender = renderMermaid("flowchart LR\n C-->D", "dark");
    await vi.waitFor(() => expect(mermaidApi.render).toHaveBeenCalledTimes(1));
    expect(mermaidApi.initialize).toHaveBeenCalledTimes(1);

    first.resolve({ svg: "<svg><text>first</text></svg>" });
    await expect(firstRender).resolves.toContain("first");
    await expect(secondRender).resolves.toContain("second");
    expect(mermaidApi.initialize).toHaveBeenLastCalledWith(
      expect.objectContaining({ theme: "dark" }),
    );
  });

  it("keeps rendering after a failed render", async () => {
    mermaidApi.parse.mockRejectedValueOnce(new Error("bad"));

    await expect(renderMermaid("bad", "light")).rejects.toThrow("bad");
    await expect(renderMermaid("flowchart LR\n A-->B", "light")).resolves.toContain(
      "ok",
    );
  });
});

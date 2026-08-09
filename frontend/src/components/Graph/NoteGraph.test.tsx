import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { GraphResponse } from "../../types/note";

// `react-force-graph-2d` paints on a `<canvas>` via a third-party force
// layout -- irrelevant to what this component is responsible for (the
// API-to-graph-data transform and the callbacks it hands the library).
// Stubbing it as a prop-capturing component lets the tests assert on
// exactly what `NoteGraph` computed and passed down, without needing a
// real canvas or force simulation in jsdom (mirrors MarkdownEditor.test.tsx's
// stubbing of @uiw/react-codemirror). A plain module-level variable, not a
// shared helper: Vitest's `vi.mock` hoisting only recognizes variables it
// can statically move above the mock call (a `mock`-prefixed `vi.fn()`, or a
// value from `vi.hoisted`) -- a value built by calling an imported factory
// isn't eligible, so each mocked file owns its own capture variable.
// biome-ignore lint/suspicious/noExplicitAny: captured props mirror whatever shape NoteGraph passes; typing them narrowly would just re-describe the library's own (untyped-here) prop surface.
let capturedProps: any = null;
vi.mock("react-force-graph-2d", () => ({
  // biome-ignore lint/suspicious/noExplicitAny: see capturedProps above.
  default: (props: any) => {
    capturedProps = props;
    return null;
  },
}));

const mockNavigate = vi.fn<() => void>();
vi.mock("react-router-dom", () => ({
  useNavigate: () => mockNavigate,
}));

const mockGetGraph = vi.fn<() => Promise<GraphResponse>>();
// `encodeNotePath` is real logic worth exercising as-is (matches
// MarkdownPreview.test.tsx's pattern) -- only `getGraph` touches the
// network and needs mocking.
vi.mock("../../api/client", async () => {
  const actual =
    await vi.importActual<typeof import("../../api/client")>("../../api/client");
  return { ...actual, getGraph: () => mockGetGraph() };
});

vi.mock("../../context/ThemeContext", () => ({
  useTheme: () => ({ theme: "light", toggleTheme: vi.fn() }),
}));

// Importing after the mocks above are registered, matching how vi.mock's
// hoisting requires them to be declared -- import placement doesn't matter
// for the hoisted calls themselves, but keeping the subject-under-test
// import last documents the dependency order for readers.
import { NoteGraph } from "./NoteGraph";

const graphResponse: GraphResponse = {
  nodes: [
    { path: "notes/a.md", title: "A", exists: true },
    { path: "notes/b.md", title: "B", exists: false },
  ],
  edges: [{ source: "notes/a.md", target: "notes/b.md" }],
};

beforeEach(() => {
  capturedProps = null;
  mockNavigate.mockClear();
  mockGetGraph.mockReset();
  mockGetGraph.mockResolvedValue(graphResponse);
});

async function renderGraph() {
  render(<NoteGraph />);
  await waitFor(() => expect(capturedProps?.graphData.nodes).toHaveLength(2));
  return capturedProps;
}

describe("NoteGraph", () => {
  it("maps each API node into graphData.nodes with an id equal to its path", async () => {
    const props = await renderGraph();

    expect(props.graphData.nodes).toEqual([
      { id: "notes/a.md", path: "notes/a.md", title: "A", exists: true },
      { id: "notes/b.md", path: "notes/b.md", title: "B", exists: false },
    ]);
  });

  it("maps each API edge into graphData.links with source/target", async () => {
    const props = await renderGraph();

    expect(props.graphData.links).toEqual([
      { source: "notes/a.md", target: "notes/b.md" },
    ]);
  });

  it("nodeColor returns a different token for exists:true than exists:false", async () => {
    const props = await renderGraph();

    const existingColor = props.nodeColor({ exists: true });
    const ghostColor = props.nodeColor({ exists: false });

    expect(existingColor).not.toBe(ghostColor);
  });

  it("onNodeClick navigates to the clicked node's encoded path when it exists", async () => {
    const props = await renderGraph();

    props.onNodeClick({ id: "notes/a.md", exists: true });

    expect(mockNavigate).toHaveBeenCalledWith("/notes/notes/a.md");
  });

  it("onNodeClick does not navigate when the clicked node does not exist", async () => {
    const props = await renderGraph();

    props.onNodeClick({ id: "notes/b.md", exists: false });

    expect(mockNavigate).not.toHaveBeenCalled();
  });
});

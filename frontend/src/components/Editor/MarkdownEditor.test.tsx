import { act, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { NoteMeta } from "../../types/note";

// The real `CodeMirror` component paints via a canvas-adjacent editing
// surface that jsdom can't fully drive, and its own internals aren't what
// this test is responsible for -- stub it as a prop-capturing component so
// the test can assert exactly what `MarkdownEditor` computed and passed
// down (matching the `NoteGraph.test.tsx` pattern for `react-force-graph-2d`).
// biome-ignore lint/suspicious/noExplicitAny: captured props mirror whatever shape MarkdownEditor passes; typing them narrowly would just re-describe react-codemirror's own prop surface.
let capturedProps: any = null;
vi.mock("@uiw/react-codemirror", () => ({
  // biome-ignore lint/suspicious/noExplicitAny: see capturedProps above.
  default: (props: any) => {
    capturedProps = props;
    return null;
  },
}));

const mockUseNotes = vi.fn();
vi.mock("../../context/NotesContext", () => ({
  useNotes: () => mockUseNotes(),
}));

const mockUseTheme = vi.fn();
vi.mock("../../context/ThemeContext", () => ({
  useTheme: () => mockUseTheme(),
}));

// `imagePasteExtension`/`noteLinkCompletionSource` have their own dedicated
// test files (imagePaste.test.ts, noteLinkCompletion.test.ts) -- here they're
// stubbed to sentinel values so this file can assert on *wiring* (are they
// called with the right notes/path, does their result land in the
// extensions array) without re-testing their internals.
const mockImagePasteExtension = vi.fn((..._args: unknown[]) => "image-paste-extension");
vi.mock("./imagePaste", () => ({
  imagePasteExtension: (...args: unknown[]) => mockImagePasteExtension(...args),
}));

const mockNoteLinkCompletionSource = vi.fn((..._args: unknown[]) => "note-link-source");
vi.mock("./noteLinkCompletion", () => ({
  noteLinkCompletionSource: (...args: unknown[]) =>
    mockNoteLinkCompletionSource(...args),
}));

import { MarkdownEditor } from "./MarkdownEditor";

const notes: NoteMeta[] = [
  { path: "notes/a.md", title: "A", tags: [], created: null, updated: null },
  { path: "notes/b.md", title: "B", tags: [], created: null, updated: null },
];

beforeEach(() => {
  capturedProps = null;
  mockUseNotes.mockReset();
  mockUseNotes.mockReturnValue({ notes, error: null, refreshNotes: vi.fn() });
  mockUseTheme.mockReset();
  mockUseTheme.mockReturnValue({ theme: "light", toggleTheme: vi.fn() });
  mockImagePasteExtension.mockClear();
  mockNoteLinkCompletionSource.mockClear();
});

describe("MarkdownEditor", () => {
  it("passes value/onChange/theme through to CodeMirror unchanged", () => {
    const onChange = vi.fn();

    render(
      <MarkdownEditor
        value="hello world"
        onChange={onChange}
        currentPath="notes/a.md"
      />,
    );

    expect(capturedProps.value).toBe("hello world");
    expect(capturedProps.onChange).toBe(onChange);
    expect(capturedProps.theme).toBe("light");
  });

  it("wires the extensions array from the current notes list and note path", () => {
    render(<MarkdownEditor value="" onChange={vi.fn()} currentPath="notes/a.md" />);

    // markdown(), autocompletion({ override: [noteLinkCompletionSource(...)] }),
    // imagePasteExtension(...) -- three entries wired in.
    expect(capturedProps.extensions).toHaveLength(3);
    expect(mockNoteLinkCompletionSource).toHaveBeenCalledWith(notes, "notes/a.md");
    expect(mockImagePasteExtension).toHaveBeenCalledWith(
      "notes/a.md",
      expect.any(Function),
    );
  });

  it("renders the error banner with role=alert when a paste error is surfaced", () => {
    render(<MarkdownEditor value="" onChange={vi.fn()} currentPath="notes/a.md" />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();

    // `imagePasteExtension`'s second argument is the `onError` callback
    // `MarkdownEditor` wires to its own error state -- invoke it the same
    // way the real extension would on a failed upload.
    const onError = mockImagePasteExtension.mock.calls[0][1] as (
      msg: string | null,
    ) => void;
    act(() => onError("upload failed: network error"));

    expect(screen.getByRole("alert")).toHaveTextContent("upload failed: network error");
  });
});

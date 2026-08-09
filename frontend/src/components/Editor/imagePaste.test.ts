import { EditorState, type Extension } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// `uploadAttachment` hits the network (via `request()`), which isn't
// available in jsdom -- mock it so each test controls exactly when/how the
// upload settles. `errorMessage` is mocked too so tests can assert the
// paste handler passes its return value straight through to `onError`
// without depending on its real `Error`-vs-`String` branching.
vi.mock("../../api/client", () => ({
  uploadAttachment: vi.fn(),
  errorMessage: vi.fn((err: unknown) => `mocked: ${String(err)}`),
}));

import { errorMessage, uploadAttachment } from "../../api/client";
import { imagePasteExtension } from "./imagePaste";

const mockUploadAttachment = vi.mocked(uploadAttachment);
const mockErrorMessage = vi.mocked(errorMessage);

// `EditorView.domEventHandlers({ paste(event, view) {...} })` returns a
// `ViewPlugin` instance whose constructor stashes the handlers object
// verbatim on `.domEventHandlers` (see @codemirror/view's ViewPlugin
// constructor) -- reaching in here lets the test call the `paste` handler
// directly with a constructed `EditorView` and a synthetic clipboard event,
// instead of trying to get jsdom to dispatch a real `ClipboardEvent` with a
// populated `DataTransfer` (which jsdom does not support).
function extractPasteHandler(
  extension: Extension,
): (event: unknown, view: EditorView) => boolean {
  const plugin = extension as unknown as {
    domEventHandlers: { paste: (event: unknown, view: EditorView) => boolean };
  };
  return plugin.domEventHandlers.paste;
}

function createView(extension: Extension): EditorView {
  const state = EditorState.create({ doc: "", extensions: [extension] });
  return new EditorView({ state, parent: document.createElement("div") });
}

function fakeClipboardItem(type: string, file: File | null) {
  return { type, getAsFile: () => file };
}

function fakePasteEvent(items: Array<{ type: string; getAsFile: () => File | null }>) {
  return {
    preventDefault: vi.fn(),
    clipboardData: { items },
  };
}

describe("imagePasteExtension", () => {
  let onError: ReturnType<typeof vi.fn<(msg: string | null) => void>>;
  let handler: (event: unknown, view: EditorView) => boolean;
  let view: EditorView;

  beforeEach(() => {
    onError = vi.fn<(msg: string | null) => void>();
    const extension = imagePasteExtension("notes/a.md", onError);
    handler = extractPasteHandler(extension);
    view = createView(extension);
  });

  afterEach(() => {
    view.destroy();
    vi.clearAllMocks();
  });

  it("inserts a placeholder synchronously and calls uploadAttachment for an image paste", () => {
    mockUploadAttachment.mockReturnValue(new Promise(() => {}));
    const file = new File(["binary"], "image.png", { type: "image/png" });
    const event = fakePasteEvent([fakeClipboardItem("image/png", file)]);

    const result = handler(event, view);

    expect(result).toBe(true);
    expect(event.preventDefault).toHaveBeenCalled();
    expect(view.state.doc.toString()).toMatch(/^!\[Uploading\.\.\.\]\(uploading:.+\)$/);
    expect(mockUploadAttachment).toHaveBeenCalledWith("notes/a.md", file);
  });

  it("replaces the placeholder with the real markdown image syntax on successful upload", async () => {
    let resolveUpload!: (result: { path: string }) => void;
    mockUploadAttachment.mockReturnValue(
      new Promise((resolve) => {
        resolveUpload = resolve;
      }),
    );
    const file = new File(["binary"], "image.png", { type: "image/png" });
    handler(fakePasteEvent([fakeClipboardItem("image/png", file)]), view);
    const placeholder = view.state.doc.toString();

    resolveUpload({ path: "notes/attachments/image.png" });

    await vi.waitFor(() => {
      expect(view.state.doc.toString()).toBe("![](notes/attachments/image.png)");
    });
    expect(view.state.doc.toString()).not.toContain(placeholder);
  });

  it("removes the placeholder and reports the error message on a failed upload", async () => {
    let rejectUpload!: (err: unknown) => void;
    mockUploadAttachment.mockReturnValue(
      new Promise((_resolve, reject) => {
        rejectUpload = reject;
      }),
    );
    const file = new File(["binary"], "image.png", { type: "image/png" });
    handler(fakePasteEvent([fakeClipboardItem("image/png", file)]), view);

    rejectUpload(new Error("upload failed"));

    await vi.waitFor(() => {
      expect(view.state.doc.toString()).toBe("");
    });
    expect(mockErrorMessage).toHaveBeenCalledWith(new Error("upload failed"));
    expect(onError).toHaveBeenLastCalledWith("mocked: Error: upload failed");
  });

  it("does not intercept a non-image paste", () => {
    const event = fakePasteEvent([fakeClipboardItem("text/plain", null)]);

    const result = handler(event, view);

    expect(result).toBe(false);
    expect(event.preventDefault).not.toHaveBeenCalled();
    expect(mockUploadAttachment).not.toHaveBeenCalled();
    expect(view.state.doc.toString()).toBe("");
  });

  it("is a no-op if the placeholder is no longer present when the upload resolves", async () => {
    let resolveUpload!: (result: { path: string }) => void;
    mockUploadAttachment.mockReturnValue(
      new Promise((resolve) => {
        resolveUpload = resolve;
      }),
    );
    const file = new File(["binary"], "image.png", { type: "image/png" });
    handler(fakePasteEvent([fakeClipboardItem("image/png", file)]), view);

    // Simulate the user clearing the placeholder before the upload settles.
    view.dispatch({
      changes: {
        from: 0,
        to: view.state.doc.length,
        insert: "something else entirely",
      },
    });

    resolveUpload({ path: "notes/attachments/image.png" });

    // Flush the microtask queue for the resolved promise's .then callback,
    // then assert the doc was left untouched by it.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(view.state.doc.toString()).toBe("something else entirely");
  });
});

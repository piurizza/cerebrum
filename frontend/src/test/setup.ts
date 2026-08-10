import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { afterEach, vi } from "vitest";

// RTL doesn't auto-register cleanup outside a Jest-detected environment, so
// register it explicitly: without this, a component left mounted by one
// test (e.g. window keydown listeners, useFocusTrap's shared activeTraps
// registry) leaks into the next. Guarded on `document` existing: this
// setup file runs for every test file regardless of its per-file
// `// @vitest-environment` override, and `cleanup()` touches `document`
// directly, which the "node" environment (src/lib/'s pure-logic tests)
// doesn't provide.
if (typeof document !== "undefined") {
  afterEach(() => {
    cleanup();
  });
}

// jsdom does not implement the Blob-URL APIs at all (both are `undefined`).
// `MarkdownPreview.tsx`'s `AttachmentImage` calls `URL.revokeObjectURL` in
// its effect cleanup, which every RTL test's automatic unmount above
// triggers -- without this stub, that throws `TypeError: ... is not a
// function` out of a React effect cleanup.
if (typeof URL.createObjectURL === "undefined") {
  URL.createObjectURL = vi.fn(() => "blob:mock");
}
if (typeof URL.revokeObjectURL === "undefined") {
  URL.revokeObjectURL = vi.fn();
}

// jsdom does not implement ResizeObserver. CodeMirror 6's EditorView
// constructs one internally to track its own DOM node's size -- this
// applies even to a directly-constructed EditorView (imagePaste.test.ts,
// noteLinkCompletion.test.ts), not just one mounted through React.
if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

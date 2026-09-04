// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
import { getEditorDirty, setEditorDirty, subscribeEditorDirty } from "./editorDirty";

afterEach(() => {
  setEditorDirty(false);
});

describe("editorDirty", () => {
  it("defaults to false", () => {
    expect(getEditorDirty()).toBe(false);
  });

  it("reflects the last write", () => {
    setEditorDirty(true);
    expect(getEditorDirty()).toBe(true);
    setEditorDirty(false);
    expect(getEditorDirty()).toBe(false);
  });

  it("notifies subscribers only on an actual change", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeEditorDirty(listener);

    setEditorDirty(true);
    setEditorDirty(true); // no-op, same value
    setEditorDirty(false);
    expect(listener).toHaveBeenCalledTimes(2);

    unsubscribe();
    setEditorDirty(true);
    expect(listener).toHaveBeenCalledTimes(2);
  });
});

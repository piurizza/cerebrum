import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { setEditorDirty } from "../lib/editorDirty";

const updateServiceWorker = vi.fn();
const setOfflineReady = vi.fn();
const setNeedRefresh = vi.fn();
let offlineReadyValue = false;
let needRefreshValue = false;
let capturedOnRegisteredSW:
  | ((swUrl: string, r: ServiceWorkerRegistration | undefined) => void)
  | undefined;

vi.mock("virtual:pwa-register/react", () => ({
  useRegisterSW: (opts?: {
    onRegisteredSW?: (swUrl: string, r: ServiceWorkerRegistration | undefined) => void;
  }) => {
    capturedOnRegisteredSW = opts?.onRegisteredSW;
    return {
      offlineReady: [offlineReadyValue, setOfflineReady],
      needRefresh: [needRefreshValue, setNeedRefresh],
      updateServiceWorker,
    };
  },
}));

import { ReloadPrompt } from "./ReloadPrompt";

beforeEach(() => {
  offlineReadyValue = false;
  needRefreshValue = false;
  capturedOnRegisteredSW = undefined;
  setEditorDirty(false);
  vi.clearAllMocks();
});

afterEach(() => {
  setEditorDirty(false);
});

describe("ReloadPrompt (U8)", () => {
  it("renders nothing when neither needRefresh nor offlineReady is set", () => {
    const { container } = render(<ReloadPrompt />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the update toast and Reload button when needRefresh is set", () => {
    needRefreshValue = true;
    render(<ReloadPrompt />);
    expect(screen.getByRole("status")).toHaveTextContent("A new version is available.");
    expect(screen.getByRole("button", { name: "Reload" })).toBeEnabled();
  });

  it("Reload calls updateServiceWorker when the editor is not dirty", async () => {
    needRefreshValue = true;
    render(<ReloadPrompt />);
    await userEvent.click(screen.getByRole("button", { name: "Reload" }));
    expect(updateServiceWorker).toHaveBeenCalledTimes(1);
  });

  it("disables Reload with helper text while the editor is dirty, then re-enables it", async () => {
    needRefreshValue = true;
    setEditorDirty(true);
    render(<ReloadPrompt />);

    const reload = screen.getByRole("button", { name: "Reload" });
    expect(reload).toBeDisabled();
    expect(screen.getByText("Save your note to update.")).toBeInTheDocument();

    act(() => setEditorDirty(false));

    expect(screen.getByRole("button", { name: "Reload" })).toBeEnabled();
    expect(screen.queryByText("Save your note to update.")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Reload" }));
    expect(updateServiceWorker).toHaveBeenCalledTimes(1);
  });

  it("shows the offline-ready toast and Dismiss clears both flags", async () => {
    offlineReadyValue = true;
    render(<ReloadPrompt />);
    expect(screen.getByRole("status")).toHaveTextContent("Cached for offline reading.");

    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(setOfflineReady).toHaveBeenCalledWith(false);
    expect(setNeedRefresh).toHaveBeenCalledWith(false);
  });

  it("needRefresh outranks offlineReady", () => {
    offlineReadyValue = true;
    needRefreshValue = true;
    render(<ReloadPrompt />);
    expect(screen.getByRole("status")).toHaveTextContent("A new version is available.");
    expect(screen.queryByText("Cached for offline reading.")).not.toBeInTheDocument();
  });

  it("clears the update() interval on unmount", () => {
    const clearSpy = vi.spyOn(globalThis, "clearInterval");
    const { unmount } = render(<ReloadPrompt />);

    act(() => {
      capturedOnRegisteredSW?.("/sw.js", {
        update: vi.fn(),
      } as unknown as ServiceWorkerRegistration);
    });

    unmount();
    expect(clearSpy).toHaveBeenCalled();
    clearSpy.mockRestore();
  });
});

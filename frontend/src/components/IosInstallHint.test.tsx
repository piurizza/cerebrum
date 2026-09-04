import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockUseOffline = vi.fn(() => ({ isOffline: false, lastSyncedAt: null }));
vi.mock("../context/OfflineContext", () => ({
  useOffline: () => mockUseOffline(),
}));

let mockStandalone = false;
vi.mock("../lib/pwaInstall", () => ({
  isStandalone: () => mockStandalone,
}));

import { IosInstallHint } from "./IosInstallHint";

const IOS_SAFARI =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1";
const IOS_CHROME =
  "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/120.0 Mobile/15E148 Safari/604.1";

function setUserAgent(ua: string) {
  Object.defineProperty(navigator, "userAgent", { value: ua, configurable: true });
}

function GoToNote() {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate("/notes/a.md")}>
      open-note
    </button>
  );
}

function renderHint(start = "/") {
  return render(
    <MemoryRouter initialEntries={[start]}>
      <IosInstallHint />
      <GoToNote />
    </MemoryRouter>,
  );
}

const hint = () => screen.queryByText("Tap Share, then Add to Home Screen.");

beforeEach(() => {
  mockStandalone = false;
  mockUseOffline.mockReturnValue({ isOffline: false, lastSyncedAt: null });
  setUserAgent(IOS_SAFARI);
  try {
    window.localStorage.clear();
  } catch {
    // ignore
  }
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("IosInstallHint (U10)", () => {
  it("does not render before a note has been opened, then appears after", async () => {
    renderHint("/");
    expect(hint()).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "open-note" }));
    expect(hint()).toBeInTheDocument();
  });

  it("does not render for iPhone Chrome (CriOS)", () => {
    setUserAgent(IOS_CHROME);
    renderHint("/notes/a.md");
    expect(hint()).not.toBeInTheDocument();
  });

  it("does not render when already installed (standalone)", () => {
    mockStandalone = true;
    renderHint("/notes/a.md");
    expect(hint()).not.toBeInTheDocument();
  });

  it("does not render when previously dismissed", () => {
    window.localStorage.setItem("cerebrum-a2hs-hint", "1");
    renderHint("/notes/a.md");
    expect(hint()).not.toBeInTheDocument();
  });

  it("does not render while offline (overlay-stack rule)", () => {
    mockUseOffline.mockReturnValue({ isOffline: true, lastSyncedAt: null });
    renderHint("/notes/a.md");
    expect(hint()).not.toBeInTheDocument();
  });

  it("Dismiss writes the flag and removes the hint", async () => {
    renderHint("/notes/a.md");
    expect(hint()).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));

    expect(hint()).not.toBeInTheDocument();
    expect(window.localStorage.getItem("cerebrum-a2hs-hint")).toBe("1");
  });

  it("swallows a localStorage write failure on dismiss", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("quota");
    });
    renderHint("/notes/a.md");

    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));

    expect(hint()).not.toBeInTheDocument();
    setItem.mockRestore();
  });
});

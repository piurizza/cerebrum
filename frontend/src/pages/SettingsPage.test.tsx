import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { InstallSection } from "./SettingsPage";

const realMatchMedia = window.matchMedia;

function setStandalone(standalone: boolean) {
  window.matchMedia = ((query: string) =>
    ({
      matches: standalone && query.includes("display-mode: standalone"),
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(() => false),
    }) as unknown as MediaQueryList) as typeof window.matchMedia;
}

function fireBeforeInstallPrompt(outcome: "accepted" | "dismissed" = "accepted") {
  const event = new Event("beforeinstallprompt");
  Object.assign(event, {
    prompt: vi.fn().mockResolvedValue(undefined),
    userChoice: Promise.resolve({ outcome }),
  });
  act(() => {
    window.dispatchEvent(event);
  });
  return event as Event & { prompt: ReturnType<typeof vi.fn> };
}

beforeEach(() => {
  setStandalone(false);
});

afterEach(() => {
  act(() => {
    window.dispatchEvent(new Event("appinstalled"));
  });
  window.matchMedia = realMatchMedia;
});

describe("InstallSection (U9)", () => {
  it("renders nothing before a beforeinstallprompt event", () => {
    const { container } = render(<InstallSection />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the Install button after the event fires", () => {
    render(<InstallSection />);
    fireBeforeInstallPrompt();
    expect(screen.getByRole("button", { name: "Install" })).toBeInTheDocument();
  });

  it("renders nothing when already running standalone", () => {
    setStandalone(true);
    render(<InstallSection />);
    fireBeforeInstallPrompt();
    expect(screen.queryByRole("button", { name: "Install" })).not.toBeInTheDocument();
  });

  it("click prompts and hides the button once installed", async () => {
    render(<InstallSection />);
    const event = fireBeforeInstallPrompt("accepted");

    await userEvent.click(screen.getByRole("button", { name: "Install" }));

    expect(event.prompt).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Install" })).not.toBeInTheDocument();
  });

  it("keeps the button after a dismissal", async () => {
    render(<InstallSection />);
    fireBeforeInstallPrompt("dismissed");

    await userEvent.click(screen.getByRole("button", { name: "Install" }));

    expect(screen.getByRole("button", { name: "Install" })).toBeInTheDocument();
  });
});

import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mockChangePassword =
  vi.fn<(currentPassword: string, newPassword: string) => Promise<void>>();
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    changePassword: (currentPassword: string, newPassword: string) =>
      mockChangePassword(currentPassword, newPassword),
  };
});

const mockUseOffline =
  vi.fn<() => { isOffline: boolean; lastSyncedAt: string | null }>();
vi.mock("../context/OfflineContext", () => ({
  useOffline: () => mockUseOffline(),
}));

import { ChangePasswordSection, InstallSection } from "./SettingsPage";

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

describe("ChangePasswordSection", () => {
  beforeEach(() => {
    mockChangePassword.mockReset();
    mockUseOffline.mockReturnValue({ isOffline: false, lastSyncedAt: null });
  });

  async function fill(
    user: ReturnType<typeof userEvent.setup>,
    current: string,
    next: string,
    confirm: string,
  ) {
    await user.type(screen.getByLabelText("Current password"), current);
    await user.type(screen.getByLabelText("New password"), next);
    await user.type(screen.getByLabelText("Confirm new password"), confirm);
    await user.click(screen.getByRole("button", { name: "Change password" }));
  }

  it("changes the password, clears the form, and says other devices were signed out", async () => {
    const user = userEvent.setup();
    mockChangePassword.mockResolvedValue(undefined);
    render(<ChangePasswordSection />);

    await fill(user, "old password here", "new password here", "new password here");

    expect(mockChangePassword).toHaveBeenCalledWith(
      "old password here",
      "new password here",
    );
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Every other device has been signed out",
    );
    expect(screen.getByLabelText("Current password")).toHaveValue("");
    expect(screen.getByLabelText("New password")).toHaveValue("");
  });

  it("rejects mismatched new passwords without calling the server", async () => {
    const user = userEvent.setup();
    render(<ChangePasswordSection />);

    await fill(
      user,
      "old password here",
      "new password here",
      "something else entirely",
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("don't match");
    expect(mockChangePassword).not.toHaveBeenCalled();
  });

  it("rejects a new password under 12 characters without calling the server", async () => {
    const user = userEvent.setup();
    render(<ChangePasswordSection />);

    await fill(user, "old password here", "short", "short");

    expect(await screen.findByRole("alert")).toHaveTextContent("at least 12");
    expect(mockChangePassword).not.toHaveBeenCalled();
  });

  it("shows the server's error and keeps the form filled when the current password is wrong", async () => {
    const user = userEvent.setup();
    mockChangePassword.mockRejectedValue(new Error("Current password is incorrect"));
    render(<ChangePasswordSection />);

    await fill(user, "wrong password", "new password here", "new password here");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Current password is incorrect",
    );
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(screen.getByLabelText("New password")).toHaveValue("new password here");
  });

  it("is disabled while offline", async () => {
    mockUseOffline.mockReturnValue({ isOffline: true, lastSyncedAt: null });
    const user = userEvent.setup();
    render(<ChangePasswordSection />);

    await user.type(screen.getByLabelText("Current password"), "old password here");
    await user.type(screen.getByLabelText("New password"), "new password here");
    await user.type(screen.getByLabelText("Confirm new password"), "new password here");

    expect(screen.getByRole("button", { name: "Change password" })).toBeDisabled();
    expect(screen.getByText(/Reconnect to the server/)).toBeInTheDocument();
  });
});

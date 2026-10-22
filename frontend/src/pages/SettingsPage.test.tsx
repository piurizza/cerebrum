import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  AccountSummary,
  ApiTokenMeta,
  AuthMethods,
  LinkedIdentity,
  OidcStartRequest,
  OidcStartResult,
} from "../types/auth";

const mockChangePassword =
  vi.fn<(currentPassword: string, newPassword: string) => Promise<void>>();
const mockGetAuthMethods = vi.fn<() => Promise<AuthMethods>>();
const mockGetLinkedIdentity = vi.fn<() => Promise<LinkedIdentity>>();
const mockStartOidc = vi.fn<(body: OidcStartRequest) => Promise<OidcStartResult>>();
const mockUnlinkIdentity = vi.fn<() => Promise<void>>();
const mockListApiTokens = vi.fn<() => Promise<ApiTokenMeta[]>>();
const mockListAccounts = vi.fn<() => Promise<AccountSummary[]>>();
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    changePassword: (currentPassword: string, newPassword: string) =>
      mockChangePassword(currentPassword, newPassword),
    getAuthMethods: () => mockGetAuthMethods(),
    getLinkedIdentity: () => mockGetLinkedIdentity(),
    startOidc: (body: OidcStartRequest) => mockStartOidc(body),
    unlinkIdentity: () => mockUnlinkIdentity(),
    listApiTokens: () => mockListApiTokens(),
    listAccounts: () => mockListAccounts(),
  };
});

const mockUseOffline =
  vi.fn<() => { isOffline: boolean; lastSyncedAt: string | null }>();
vi.mock("../context/OfflineContext", () => ({
  useOffline: () => mockUseOffline(),
}));

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({ username: null }),
}));

const mockRedirectTo = vi.fn<(url: string) => void>();
vi.mock("../lib/redirect", () => ({
  redirectTo: (url: string) => mockRedirectTo(url),
}));

import { ApiError } from "../api/client";
import { oidcErrorMessage } from "../lib/oidcErrors";
import { ChangePasswordSection, InstallSection, SettingsPage } from "./SettingsPage";

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

const KEYCLOAK: AuthMethods = {
  password_login: true,
  oidc: { provider_name: "Keycloak" },
  setup_required: false,
};

function identity(overrides: Partial<LinkedIdentity> = {}): LinkedIdentity {
  return {
    linked: false,
    provider_name: "Keycloak",
    display_name: null,
    has_password: true,
    password_usable: true,
    ...overrides,
  };
}

const LINKED_WITH_PASSWORD = identity({
  linked: true,
  display_name: "ana@example.com",
});
// Created through the provider: no password at all.
const PROVIDER_ONLY = identity({
  linked: true,
  display_name: "bea@example.com",
  has_password: false,
  password_usable: false,
});
// A linked non-admin while password login is switched off: the password
// exists but no longer signs them in.
const PASSWORD_SWITCHED_OFF = identity({
  linked: true,
  display_name: "cal@example.com",
  has_password: true,
  password_usable: false,
});

function renderSettings(entry = "/settings") {
  const router = createMemoryRouter(
    [{ path: "/settings", element: <SettingsPage /> }],
    {
      initialEntries: [entry],
    },
  );
  render(<RouterProvider router={router} />);
  return router;
}

function providerSection() {
  return screen.getByRole("region", { name: "Sign-in provider" });
}

async function findProviderSection() {
  return screen.findByRole("region", { name: "Sign-in provider" });
}

describe("SettingsPage sign-in provider section", () => {
  beforeEach(() => {
    mockUseOffline.mockReturnValue({ isOffline: false, lastSyncedAt: null });
    mockGetAuthMethods.mockReset();
    mockGetLinkedIdentity.mockReset();
    mockStartOidc.mockReset();
    mockUnlinkIdentity.mockReset();
    mockRedirectTo.mockReset();
    mockListApiTokens.mockReset();
    mockListApiTokens.mockResolvedValue([]);
    mockListAccounts.mockReset();
    mockListAccounts.mockRejectedValue(new ApiError("Forbidden", 403));
    mockGetAuthMethods.mockResolvedValue(KEYCLOAK);
  });

  it("is hidden when no provider is configured, and change-password stays", async () => {
    mockGetAuthMethods.mockResolvedValue({
      password_login: true,
      oidc: null,
      setup_required: false,
    });
    mockGetLinkedIdentity.mockResolvedValue(identity({ provider_name: null }));
    renderSettings();

    await waitFor(() => expect(mockGetLinkedIdentity).toHaveBeenCalled());
    await waitFor(() => expect(mockGetAuthMethods).toHaveBeenCalled());
    expect(screen.queryByRole("region", { name: "Sign-in provider" })).toBeNull();
    expect(screen.queryByText(/Keycloak/)).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Change password" }),
    ).toBeInTheDocument();
  });

  it("shows a loading placeholder until the identity call resolves", async () => {
    let resolve!: (value: LinkedIdentity) => void;
    mockGetLinkedIdentity.mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    renderSettings();

    const section = await findProviderSection();
    expect(within(section).getByText("Loading...")).toBeInTheDocument();
    expect(within(section).queryByRole("button")).toBeNull();

    await act(async () => {
      resolve(LINKED_WITH_PASSWORD);
    });
    expect(within(section).queryByText("Loading...")).toBeNull();
    expect(within(section).getByText("ana@example.com")).toBeInTheDocument();
  });

  it("shows the linked display name and an enabled Unlink for a password account", async () => {
    mockGetLinkedIdentity.mockResolvedValue(LINKED_WITH_PASSWORD);
    renderSettings();

    const section = await findProviderSection();
    expect(await within(section).findByText("ana@example.com")).toBeInTheDocument();
    expect(within(section).getByRole("button", { name: "Unlink" })).toBeEnabled();
    expect(within(section).queryByRole("button", { name: /^Link/ })).toBeNull();
    expect(
      screen.getByRole("heading", { name: "Change password" }),
    ).toBeInTheDocument();
  });

  it("unlinks after confirmation and reloads the identity", async () => {
    mockGetLinkedIdentity
      .mockResolvedValueOnce(LINKED_WITH_PASSWORD)
      .mockResolvedValue(identity());
    mockUnlinkIdentity.mockResolvedValue(undefined);
    const user = userEvent.setup();
    renderSettings();

    const section = await findProviderSection();
    await user.click(await within(section).findByRole("button", { name: "Unlink" }));
    expect(mockUnlinkIdentity).not.toHaveBeenCalled();

    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Unlink" }));

    expect(mockUnlinkIdentity).toHaveBeenCalledTimes(1);
    expect(
      await within(section).findByRole("button", { name: "Link Keycloak account" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("shows an unlink refusal inline in an alert", async () => {
    mockGetLinkedIdentity.mockResolvedValue(LINKED_WITH_PASSWORD);
    mockUnlinkIdentity.mockRejectedValue(
      new ApiError("You need a password you can sign in with before unlinking", 409),
    );
    const user = userEvent.setup();
    renderSettings();

    const section = await findProviderSection();
    await user.click(await within(section).findByRole("button", { name: "Unlink" }));
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Unlink" }),
    );

    expect(
      await within(screen.getByRole("dialog")).findByRole("alert"),
    ).toHaveTextContent("You need a password you can sign in with before unlinking");
  });

  it("provider-only account: Unlink disabled with an explanation, and no change-password section", async () => {
    mockGetLinkedIdentity.mockResolvedValue(PROVIDER_ONLY);
    renderSettings();

    const section = await findProviderSection();
    expect(await within(section).findByText("bea@example.com")).toBeInTheDocument();
    expect(within(section).getByRole("button", { name: "Unlink" })).toBeDisabled();
    expect(within(section).getByText(/would lock you out/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Change password" })).toBeNull();
  });

  it("linked non-admin with password login off: no change-password, Unlink disabled with its explanation", async () => {
    mockGetLinkedIdentity.mockResolvedValue(PASSWORD_SWITCHED_OFF);
    renderSettings();

    const section = await findProviderSection();
    expect(await within(section).findByText("cal@example.com")).toBeInTheDocument();
    const unlink = within(section).getByRole("button", { name: "Unlink" });
    expect(unlink).toBeDisabled();
    expect(unlink).toHaveAccessibleDescription(/would lock you out/);
    expect(screen.queryByRole("heading", { name: "Change password" })).toBeNull();
  });

  it("keeps the change-password section when the identity call fails", async () => {
    mockGetLinkedIdentity.mockRejectedValue(new Error("boom"));
    renderSettings();

    const section = await findProviderSection();
    expect(await within(section).findByRole("alert")).toHaveTextContent(
      "Could not load your sign-in provider link",
    );
    expect(
      screen.getByRole("heading", { name: "Change password" }),
    ).toBeInTheDocument();
  });

  it("links after asking for the current password", async () => {
    mockGetLinkedIdentity.mockResolvedValue(identity());
    mockStartOidc.mockResolvedValue({ authorization_url: "https://idp.example/auth" });
    const user = userEvent.setup();
    renderSettings();

    const section = await findProviderSection();
    const link = await within(section).findByRole("button", {
      name: "Link Keycloak account",
    });
    expect(link).toBeDisabled();

    await user.type(within(section).getByLabelText("Current password"), "my password");
    await user.click(link);

    expect(mockStartOidc).toHaveBeenCalledWith({
      intent: "link",
      current_password: "my password",
    });
    await waitFor(() =>
      expect(mockRedirectTo).toHaveBeenCalledWith("https://idp.example/auth"),
    );
  });

  it("links without a password prompt when the account has none", async () => {
    mockGetLinkedIdentity.mockResolvedValue(
      identity({ has_password: false, password_usable: false }),
    );
    mockStartOidc.mockResolvedValue({ authorization_url: "https://idp.example/auth" });
    const user = userEvent.setup();
    renderSettings();

    const section = await findProviderSection();
    await user.click(
      await within(section).findByRole("button", { name: "Link Keycloak account" }),
    );

    expect(within(section).queryByLabelText("Current password")).toBeNull();
    expect(mockStartOidc).toHaveBeenCalledWith({ intent: "link" });
  });

  it("shows a wrong current password inline", async () => {
    mockGetLinkedIdentity.mockResolvedValue(identity());
    mockStartOidc.mockRejectedValue(new ApiError("Current password is incorrect", 403));
    const user = userEvent.setup();
    renderSettings();

    const section = await findProviderSection();
    await user.type(
      await within(section).findByLabelText("Current password"),
      "wrong password",
    );
    await user.click(
      within(section).getByRole("button", { name: "Link Keycloak account" }),
    );

    expect(await within(section).findByRole("alert")).toHaveTextContent(
      "Current password is incorrect",
    );
    expect(mockRedirectTo).not.toHaveBeenCalled();
    expect(
      within(section).getByRole("button", { name: "Link Keycloak account" }),
    ).toBeEnabled();
  });

  it("shows ?oidc_error from a failed link and removes it from the URL", async () => {
    mockGetLinkedIdentity.mockResolvedValue(identity());
    const router = renderSettings("/settings?oidc_error=already_linked");

    const section = await findProviderSection();
    expect(await within(section).findByRole("alert")).toHaveTextContent(
      oidcErrorMessage("already_linked") ?? "missing",
    );
    await waitFor(() => expect(router.state.location.search).toBe(""));
  });

  it("disables Link while offline, with the reconnect hint", async () => {
    mockUseOffline.mockReturnValue({ isOffline: true, lastSyncedAt: null });
    mockGetLinkedIdentity.mockResolvedValue(identity());
    const user = userEvent.setup();
    renderSettings();

    const section = await findProviderSection();
    await user.type(await within(section).findByLabelText("Current password"), "pw");
    expect(
      within(section).getByRole("button", { name: "Link Keycloak account" }),
    ).toBeDisabled();
    expect(within(section).getByText(/Reconnect to the server/)).toBeInTheDocument();
  });

  it("disables Unlink while offline, with the reconnect hint", async () => {
    mockUseOffline.mockReturnValue({ isOffline: true, lastSyncedAt: null });
    mockGetLinkedIdentity.mockResolvedValue(LINKED_WITH_PASSWORD);
    renderSettings();

    const section = await findProviderSection();
    expect(
      await within(section).findByRole("button", { name: "Unlink" }),
    ).toBeDisabled();
    expect(within(section).getByText(/Reconnect to the server/)).toBeInTheDocument();
    expect(providerSection()).toBe(section);
  });
});

import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthMethods, OidcStartRequest, OidcStartResult } from "../types/auth";

const mockGetAuthMethods = vi.fn<() => Promise<AuthMethods>>();
const mockStartOidc = vi.fn<(body: OidcStartRequest) => Promise<OidcStartResult>>();
const mockRegister =
  vi.fn<(username: string, password: string, token: string) => Promise<void>>();
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    getAuthMethods: () => mockGetAuthMethods(),
    startOidc: (body: OidcStartRequest) => mockStartOidc(body),
    register: (username: string, password: string, token: string) =>
      mockRegister(username, password, token),
  };
});

const mockRedirectTo = vi.fn<(url: string) => void>();
vi.mock("../lib/redirect", () => ({
  redirectTo: (url: string) => mockRedirectTo(url),
}));

import { ApiError } from "../api/client";
import { oidcErrorMessage } from "../lib/oidcErrors";
import { RegisterPage } from "./RegisterPage";

const NO_PROVIDER: AuthMethods = {
  password_login: true,
  oidc: null,
  setup_required: false,
};
const KEYCLOAK: AuthMethods = {
  password_login: true,
  oidc: { provider_name: "Keycloak" },
  setup_required: false,
};
const KEYCLOAK_ONLY: AuthMethods = {
  password_login: false,
  oidc: { provider_name: "Keycloak" },
  setup_required: false,
};

function renderRegister(entry = "/register") {
  const router = createMemoryRouter(
    [
      { path: "/register", element: <RegisterPage /> },
      { path: "/login", element: <div>login page</div> },
    ],
    { initialEntries: [entry] },
  );
  render(<RouterProvider router={router} />);
  return router;
}

function formShape(): string[] {
  const form = screen.getByRole("heading", { name: "Register" }).closest("form");
  return Array.from(form?.children ?? []).map((child) => {
    const label =
      child.tagName === "LABEL" ? child.firstChild?.textContent?.trim() : "";
    const text = child.tagName === "BUTTON" ? child.textContent : "";
    return `${child.tagName.toLowerCase()}${label ? `:${label}` : ""}${text ? `:${text}` : ""}`;
  });
}

beforeEach(() => {
  mockGetAuthMethods.mockReset();
  mockStartOidc.mockReset();
  mockRegister.mockReset();
  mockRedirectTo.mockReset();
});

describe("RegisterPage without a provider", () => {
  it("renders today's form in today's order", async () => {
    mockGetAuthMethods.mockResolvedValue(NO_PROVIDER);
    renderRegister();

    await waitFor(() => expect(screen.getByLabelText("Username")).toBeEnabled());
    expect(formShape()).toEqual([
      "h1",
      "label:Username",
      "label:Password",
      "label:Invite token",
      "button:Register",
      "p",
    ]);
    expect(
      screen.queryByRole("button", { name: /Sign up with/ }),
    ).not.toBeInTheDocument();
  });

  it("still registers with a password and sends the person to log in", async () => {
    mockGetAuthMethods.mockResolvedValue(NO_PROVIDER);
    mockRegister.mockResolvedValue(undefined);
    const user = userEvent.setup();
    const router = renderRegister();

    await waitFor(() => expect(screen.getByLabelText("Username")).toBeEnabled());
    await user.type(screen.getByLabelText("Username"), "ana");
    await user.type(screen.getByLabelText("Password"), "a long password");
    await user.type(screen.getByLabelText("Invite token"), "invite-123");
    await user.click(screen.getByRole("button", { name: "Register" }));

    expect(mockRegister).toHaveBeenCalledWith("ana", "a long password", "invite-123");
    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
  });
});

describe("RegisterPage while the sign-in options load", () => {
  it("disables the controls while pending", async () => {
    let resolve!: (methods: AuthMethods) => void;
    mockGetAuthMethods.mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    renderRegister();

    expect(screen.getByLabelText("Username")).toBeDisabled();
    expect(screen.getByLabelText("Password")).toBeDisabled();
    expect(screen.getByLabelText("Invite token")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Register" })).toBeDisabled();

    await act(async () => {
      resolve(KEYCLOAK);
    });
    expect(screen.getByRole("button", { name: "Sign up with Keycloak" })).toBeEnabled();
  });

  it("falls back to the password form with a notice and no provider button on failure", async () => {
    mockGetAuthMethods.mockRejectedValue(new TypeError("Failed to fetch"));
    renderRegister();

    expect(
      await screen.findByText("Could not load sign-in options"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeEnabled();
    expect(screen.getByRole("button", { name: "Register" })).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: /Sign up with/ }),
    ).not.toBeInTheDocument();
  });
});

describe("RegisterPage with a provider", () => {
  it("puts username and invite first, then the provider button, then the password part", async () => {
    mockGetAuthMethods.mockResolvedValue(KEYCLOAK);
    renderRegister();

    await screen.findByRole("button", { name: "Sign up with Keycloak" });
    expect(formShape()).toEqual([
      "h1",
      "label:Username",
      "label:Invite token",
      "button:Sign up with Keycloak",
      "p",
      "label:Password",
      "button:Register",
      "p",
    ]);
    expect(
      screen.getByRole("button", { name: "Sign up with Keycloak" }),
    ).toHaveAttribute("type", "button");
  });

  it("omits the password part when password login is off", async () => {
    mockGetAuthMethods.mockResolvedValue(KEYCLOAK_ONLY);
    renderRegister();

    await screen.findByRole("button", { name: "Sign up with Keycloak" });
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Register" })).not.toBeInTheDocument();
  });

  it("keeps the first-admin password form on a fresh install even with password login off", async () => {
    mockGetAuthMethods.mockResolvedValue({ ...KEYCLOAK_ONLY, setup_required: true });
    mockRegister.mockResolvedValue();
    const user = userEvent.setup();
    const router = renderRegister();

    await screen.findByRole("button", { name: "Sign up with Keycloak" });
    await user.type(screen.getByLabelText("Username"), "owner");
    await user.type(screen.getByLabelText("Password"), "ownerpassword1");
    await user.type(screen.getByLabelText("Invite token"), "setup-token");
    await user.click(screen.getByRole("button", { name: "Register" }));

    await waitFor(() => expect(router.state.location.pathname).toBe("/login"));
    expect(mockRegister).toHaveBeenCalledWith("owner", "ownerpassword1", "setup-token");
    expect(mockStartOidc).not.toHaveBeenCalled();
  });

  it("validates an empty invite itself and makes no request", async () => {
    mockGetAuthMethods.mockResolvedValue(KEYCLOAK);
    const user = userEvent.setup();
    renderRegister();

    await user.type(await screen.findByLabelText("Username"), "ana");
    await user.click(screen.getByRole("button", { name: "Sign up with Keycloak" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Enter your invite token",
    );
    expect(screen.getByLabelText("Invite token")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(screen.getByLabelText("Invite token")).toHaveFocus();
    expect(mockStartOidc).not.toHaveBeenCalled();
  });

  it("validates an empty username itself and makes no request", async () => {
    mockGetAuthMethods.mockResolvedValue(KEYCLOAK);
    const user = userEvent.setup();
    renderRegister();

    await user.type(await screen.findByLabelText("Invite token"), "invite-123");
    await user.click(screen.getByRole("button", { name: "Sign up with Keycloak" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Choose a username");
    expect(screen.getByLabelText("Username")).toHaveAttribute("aria-invalid", "true");
    expect(mockStartOidc).not.toHaveBeenCalled();
  });

  it("starts a register round trip with the username and invite, never putting the invite in the URL", async () => {
    mockGetAuthMethods.mockResolvedValue(KEYCLOAK);
    mockStartOidc.mockResolvedValue({ authorization_url: "https://idp.example/auth" });
    const user = userEvent.setup();
    const router = renderRegister();

    await user.type(await screen.findByLabelText("Username"), "ana");
    await user.type(screen.getByLabelText("Invite token"), "invite-123");
    await user.click(screen.getByRole("button", { name: "Sign up with Keycloak" }));

    expect(mockStartOidc).toHaveBeenCalledWith({
      intent: "register",
      username: "ana",
      invite_token: "invite-123",
    });
    await waitFor(() =>
      expect(mockRedirectTo).toHaveBeenCalledWith("https://idp.example/auth"),
    );
    expect(router.state.location.search).not.toContain("invite-123");
  });

  it("shows 'Username already taken' inline on a 409 from start", async () => {
    mockGetAuthMethods.mockResolvedValue(KEYCLOAK);
    mockStartOidc.mockRejectedValue(new ApiError("Username already taken", 409));
    const user = userEvent.setup();
    renderRegister();

    await user.type(await screen.findByLabelText("Username"), "ana");
    await user.type(screen.getByLabelText("Invite token"), "invite-123");
    const button = screen.getByRole("button", { name: "Sign up with Keycloak" });
    await user.click(button);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Username already taken",
    );
    expect(button).toBeEnabled();
    expect(mockRedirectTo).not.toHaveBeenCalled();
  });

  it("reads ?oidc_error=username_taken&username=ana, shows the message, prefills, and cleans the URL", async () => {
    mockGetAuthMethods.mockResolvedValue(KEYCLOAK);
    const router = renderRegister("/register?oidc_error=username_taken&username=ana");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      oidcErrorMessage("username_taken") ?? "missing",
    );
    expect(screen.getByLabelText("Username")).toHaveValue("ana");
    await waitFor(() => expect(router.state.location.search).toBe(""));
  });
});

import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthMethods, OidcStartRequest, OidcStartResult } from "../types/auth";

const mockGetAuthMethods = vi.fn<() => Promise<AuthMethods>>();
const mockStartOidc = vi.fn<(body: OidcStartRequest) => Promise<OidcStartResult>>();
vi.mock("../api/client", async () => {
  const actual = await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    getAuthMethods: () => mockGetAuthMethods(),
    startOidc: (body: OidcStartRequest) => mockStartOidc(body),
  };
});

const mockLogin = vi.fn<(username: string, password: string) => Promise<void>>();
vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({ login: mockLogin }),
}));

const mockRedirectTo = vi.fn<(url: string) => void>();
vi.mock("../lib/redirect", () => ({
  redirectTo: (url: string) => mockRedirectTo(url),
}));

// The provider button must leave the logout tombstone alone (KTD13): only
// AuthContext clears it, and only after a successful round trip.
const mockConsumeLoggedOut = vi.fn<() => boolean>(() => false);
const mockMarkLoggedOut = vi.fn<() => void>();
vi.mock("../lib/sessionEstablished", async () => {
  const actual = await vi.importActual<typeof import("../lib/sessionEstablished")>(
    "../lib/sessionEstablished",
  );
  return {
    ...actual,
    consumeLoggedOut: () => mockConsumeLoggedOut(),
    markLoggedOut: () => mockMarkLoggedOut(),
  };
});

import { GENERIC_OIDC_ERROR, oidcErrorMessage } from "../lib/oidcErrors";
import { LoginPage } from "./LoginPage";

const NO_PROVIDER: AuthMethods = { password_login: true, oidc: null };
const KEYCLOAK: AuthMethods = {
  password_login: true,
  oidc: { provider_name: "Keycloak" },
};
const KEYCLOAK_ONLY: AuthMethods = {
  password_login: false,
  oidc: { provider_name: "Keycloak" },
};

function renderLogin(entry = "/login") {
  const router = createMemoryRouter(
    [
      { path: "/login", element: <LoginPage /> },
      { path: "/register", element: <div>register page</div> },
      { path: "/", element: <div>home page</div> },
    ],
    { initialEntries: [entry] },
  );
  render(<RouterProvider router={router} />);
  return router;
}

beforeEach(() => {
  mockGetAuthMethods.mockReset();
  mockStartOidc.mockReset();
  mockLogin.mockReset();
  mockRedirectTo.mockReset();
  mockConsumeLoggedOut.mockClear();
  mockMarkLoggedOut.mockClear();
});

describe("LoginPage without a provider", () => {
  it("renders exactly today's form: heading, username, password, Log in, register link", async () => {
    mockGetAuthMethods.mockResolvedValue(NO_PROVIDER);
    renderLogin();

    await waitFor(() => expect(screen.getByLabelText("Username")).toBeEnabled());

    const form = screen.getByRole("heading", { name: "Log in" }).closest("form");
    expect(form).toHaveClass("auth-form");
    const shape = Array.from(form?.children ?? []).map(
      (child) => `${child.tagName.toLowerCase()}.${child.className}`,
    );
    expect(shape).toEqual([
      "h1.",
      "label.rename-field",
      "label.rename-field",
      "button.btn btn-primary btn-block",
      "p.auth-switch",
    ]);
    expect(screen.getByLabelText("Password")).toBeEnabled();
    expect(screen.getByRole("button", { name: "Log in" })).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: /Sign in with/ }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("still signs in with a password", async () => {
    mockGetAuthMethods.mockResolvedValue(NO_PROVIDER);
    mockLogin.mockResolvedValue(undefined);
    const user = userEvent.setup();
    const router = renderLogin();

    await waitFor(() => expect(screen.getByLabelText("Username")).toBeEnabled());
    await user.type(screen.getByLabelText("Username"), "ana");
    await user.type(screen.getByLabelText("Password"), "secret password");
    await user.click(screen.getByRole("button", { name: "Log in" }));

    expect(mockLogin).toHaveBeenCalledWith("ana", "secret password");
    await waitFor(() => expect(router.state.location.pathname).toBe("/"));
  });
});

describe("LoginPage while the sign-in options load", () => {
  it("disables the controls until the methods call settles", async () => {
    let resolve!: (methods: AuthMethods) => void;
    mockGetAuthMethods.mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    renderLogin();

    expect(screen.getByLabelText("Username")).toBeDisabled();
    expect(screen.getByLabelText("Password")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Log in" })).toBeDisabled();

    await act(async () => {
      resolve(KEYCLOAK);
    });

    expect(screen.getByLabelText("Username")).toBeEnabled();
    expect(screen.getByRole("button", { name: "Sign in with Keycloak" })).toBeEnabled();
  });

  it("falls back to the password form with a notice and a retry when the call fails", async () => {
    mockGetAuthMethods.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const user = userEvent.setup();
    renderLogin();

    expect(
      await screen.findByText("Could not load sign-in options"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Username")).toBeEnabled();
    expect(screen.getByLabelText("Password")).toBeEnabled();
    expect(screen.getByRole("button", { name: "Log in" })).toBeEnabled();
    expect(
      screen.queryByRole("button", { name: /Sign in with/ }),
    ).not.toBeInTheDocument();

    mockGetAuthMethods.mockResolvedValueOnce(KEYCLOAK);
    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(
      await screen.findByRole("button", { name: "Sign in with Keycloak" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Could not load sign-in options"),
    ).not.toBeInTheDocument();
    expect(mockGetAuthMethods).toHaveBeenCalledTimes(2);
  });
});

describe("LoginPage with a provider", () => {
  it("starts a login round trip and navigates to the provider, leaving the tombstone alone", async () => {
    mockGetAuthMethods.mockResolvedValue(KEYCLOAK);
    mockStartOidc.mockResolvedValue({
      authorization_url: "https://idp.example/authorize?state=abc",
    });
    const user = userEvent.setup();
    renderLogin();

    await user.click(
      await screen.findByRole("button", { name: "Sign in with Keycloak" }),
    );

    expect(mockStartOidc).toHaveBeenCalledWith({ intent: "login" });
    await waitFor(() =>
      expect(mockRedirectTo).toHaveBeenCalledWith(
        "https://idp.example/authorize?state=abc",
      ),
    );
    expect(mockConsumeLoggedOut).not.toHaveBeenCalled();
    expect(mockMarkLoggedOut).not.toHaveBeenCalled();
    // Password login is on, so the password form is still there.
    expect(screen.getByLabelText("Username")).toBeInTheDocument();
  });

  it("disables the button while the start request is pending", async () => {
    mockGetAuthMethods.mockResolvedValue(KEYCLOAK);
    mockStartOidc.mockReturnValue(new Promise(() => {}));
    const user = userEvent.setup();
    renderLogin();

    const button = await screen.findByRole("button", { name: "Sign in with Keycloak" });
    await user.click(button);

    expect(button).toBeDisabled();
    await user.click(button);
    expect(mockStartOidc).toHaveBeenCalledTimes(1);
  });

  it("shows a start failure inline and re-enables the button", async () => {
    mockGetAuthMethods.mockResolvedValue(KEYCLOAK);
    mockStartOidc.mockRejectedValue(
      new Error("The sign-in provider could not be reached"),
    );
    const user = userEvent.setup();
    renderLogin();

    const button = await screen.findByRole("button", { name: "Sign in with Keycloak" });
    await user.click(button);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The sign-in provider could not be reached",
    );
    expect(button).toBeEnabled();
    expect(mockRedirectTo).not.toHaveBeenCalled();
  });

  it("shows ?oidc_error=not_linked as an alert and removes it from the URL", async () => {
    mockGetAuthMethods.mockResolvedValue(KEYCLOAK);
    const router = renderLogin("/login?oidc_error=not_linked");

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(oidcErrorMessage("not_linked") ?? "missing");
    expect(alert).toHaveTextContent(/invite/);
    await waitFor(() => expect(router.state.location.search).toBe(""));
    expect(router.state.location.pathname).toBe("/login");
    // Still shown after the parameter is gone.
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("shows the generic message for an unknown oidc_error, never the raw value", async () => {
    mockGetAuthMethods.mockResolvedValue(KEYCLOAK);
    const router = renderLogin(
      "/login?oidc_error=%3Cb%3Eyou%20were%20hacked%3C%2Fb%3E",
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(GENERIC_OIDC_ERROR);
    expect(screen.queryByText(/you were hacked/)).not.toBeInTheDocument();
    await waitFor(() => expect(router.state.location.search).toBe(""));
  });
});

describe("LoginPage with password login switched off", () => {
  it("hides the password fields behind a 'Sign in with a password' toggle", async () => {
    mockGetAuthMethods.mockResolvedValue(KEYCLOAK_ONLY);
    const user = userEvent.setup();
    renderLogin();

    const toggle = await screen.findByRole("button", {
      name: "Sign in with a password",
    });
    expect(
      screen.getByRole("button", { name: "Sign in with Keycloak" }),
    ).toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    const controlsId = toggle.getAttribute("aria-controls");
    expect(controlsId).toBeTruthy();
    expect(document.getElementById(controlsId ?? "")).not.toBeNull();
    expect(screen.queryByLabelText("Username")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Log in" })).not.toBeInTheDocument();

    await user.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByLabelText("Username")).toHaveFocus();
    expect(screen.getByLabelText("Password")).toBeVisible();
    expect(document.getElementById(controlsId ?? "")).toContainElement(
      screen.getByLabelText("Username"),
    );
  });

  it("stays open after a failed password attempt", async () => {
    mockGetAuthMethods.mockResolvedValue(KEYCLOAK_ONLY);
    mockLogin.mockRejectedValue(new Error("Invalid username or password"));
    const user = userEvent.setup();
    renderLogin();

    await user.click(
      await screen.findByRole("button", { name: "Sign in with a password" }),
    );
    await user.type(screen.getByLabelText("Username"), "admin");
    await user.type(screen.getByLabelText("Password"), "wrong password");
    await user.click(screen.getByRole("button", { name: "Log in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Invalid username or password",
    );
    expect(screen.getByLabelText("Username")).toHaveValue("admin");
    expect(
      screen.getByRole("button", { name: "Sign in with a password" }),
    ).toHaveAttribute("aria-expanded", "true");
  });
});

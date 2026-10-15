import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// RootLayout's `loading` gate is now seeded by AuthProvider from the
// session-established marker (KTD-B): a returning browser must paint the
// routed content immediately, with no full-screen "Loading..." stall,
// while a genuine first visit still shows the gate until the mount refresh
// resolves. This exercises the real AuthProvider end to end with the marker
// module and the API client mocked.

const mockRefreshAccessToken = vi.fn<() => Promise<string | null>>();
const mockWasSessionEstablished = vi.fn<() => boolean>(() => false);

vi.mock("./api/client", () => ({
  login: vi.fn(),
  refreshAccessToken: () => mockRefreshAccessToken(),
  refreshFailureWasAuthRejection: () => false,
  setAccessToken: vi.fn(),
  setOnRefreshFailure: vi.fn(),
}));

vi.mock("./lib/sessionEstablished", () => ({
  wasSessionEstablished: () => mockWasSessionEstablished(),
  consumeLoggedOut: () => false,
  markSessionEstablished: vi.fn(),
  clearSessionEstablished: vi.fn(),
  markLoggedOut: vi.fn(),
}));

// ReloadPrompt owns the single useRegisterSW / virtual:pwa-register
// consumer -- stubbed so RootLayout can render without the SW plumbing.
vi.mock("./components/ReloadPrompt", () => ({ ReloadPrompt: () => null }));

import { RootLayout } from "./App";
import { AuthProvider } from "./context/AuthContext";

beforeEach(() => {
  mockRefreshAccessToken.mockReset();
  // A refresh that never settles -- the seed must not depend on it.
  mockRefreshAccessToken.mockReturnValue(new Promise(() => {}));
  mockWasSessionEstablished.mockReset();
  mockWasSessionEstablished.mockReturnValue(false);
});

afterEach(() => {
  vi.clearAllMocks();
});

function renderRootLayout() {
  const router = createMemoryRouter(
    [
      {
        element: <RootLayout />,
        children: [{ path: "/", element: <div>routed content</div> }],
      },
    ],
    { initialEntries: ["/"] },
  );
  return render(
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>,
  );
}

describe("RootLayout loading gate", () => {
  it("renders the routed content immediately when a session is on record, without waiting for refresh", () => {
    mockWasSessionEstablished.mockReturnValue(true);

    renderRootLayout();

    // Synchronous -- no `await`. AuthProvider seeded loading=false.
    expect(screen.getByText("routed content")).toBeInTheDocument();
    expect(screen.queryByText("Loading...")).not.toBeInTheDocument();
  });

  it("shows the Loading gate on a genuine first visit while the mount refresh is pending", () => {
    mockWasSessionEstablished.mockReturnValue(false);

    renderRootLayout();

    expect(screen.getByText("Loading...")).toBeInTheDocument();
    expect(screen.queryByText("routed content")).not.toBeInTheDocument();
  });
});

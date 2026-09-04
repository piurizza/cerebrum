import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

const mockIsZen = vi.fn<() => boolean>(() => false);

vi.mock("./context/AuthContext", () => ({
  useAuth: () => ({ logout: vi.fn() }),
}));
vi.mock("./context/ZenModeContext", () => ({
  useZenMode: () => ({ isZen: mockIsZen(), toggleZen: vi.fn() }),
  ZenModeProvider: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("./components/OfflineBanner", () => ({ OfflineBanner: () => null }));
vi.mock("./components/IosInstallHint", () => ({ IosInstallHint: () => null }));
// Uncontrolled input: its value survives parent re-renders but not an
// unmount -- exactly the signal for "the drawer subtree is hidden with
// CSS, never conditionally rendered".
vi.mock("./components/NoteBrowser/NoteBrowser", () => ({
  NoteBrowser: () => <input aria-label="note-search-stub" defaultValue="" />,
}));
vi.mock("./pages/GraphViewPage", () => ({
  GraphViewPage: () => <div>graph page</div>,
}));
vi.mock("./pages/TasksPage", () => ({ TasksPage: () => <div>tasks page</div> }));
vi.mock("./pages/SettingsPage", () => ({
  SettingsPage: () => <div>settings page</div>,
}));
vi.mock("./pages/NoteViewPage", () => ({
  NoteViewPage: () => <div>note page</div>,
}));

import { AppShell } from "./App";

function setViewport(isMobile: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: isMobile && query.includes("max-width: 768px"),
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(() => false),
  })) as unknown as typeof window.matchMedia;
}

function renderShell(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppShell />
    </MemoryRouter>,
  );
}

const sidebar = () => document.getElementById("app-sidebar") as HTMLElement;
const menu = () => screen.getByRole("button", { name: "Menu" });

afterEach(() => {
  mockIsZen.mockReturnValue(false);
  setViewport(false);
});

describe("AppShell mobile drawer (U2)", () => {
  it("toggles the drawer and tracks aria-expanded on the hamburger", async () => {
    setViewport(true);
    renderShell();

    expect(menu()).toHaveAttribute("aria-expanded", "false");
    expect(sidebar().className).not.toContain("is-open");

    await userEvent.click(menu());
    expect(menu()).toHaveAttribute("aria-expanded", "true");
    expect(sidebar().className).toContain("is-open");

    await userEvent.click(menu());
    expect(menu()).toHaveAttribute("aria-expanded", "false");
    expect(sidebar().className).not.toContain("is-open");
  });

  it("closes on navigation and returns focus to the hamburger", async () => {
    setViewport(true);
    renderShell();

    await userEvent.click(menu());
    expect(sidebar().className).toContain("is-open");

    await userEvent.click(screen.getByRole("link", { name: "Graph" }));

    expect(sidebar().className).not.toContain("is-open");
    expect(document.activeElement).toBe(menu());
  });

  it("closes on Escape and returns focus to the hamburger", async () => {
    setViewport(true);
    renderShell();

    await userEvent.click(menu());
    await userEvent.keyboard("{Escape}");

    expect(sidebar().className).not.toContain("is-open");
    expect(document.activeElement).toBe(menu());
  });

  it("closes on backdrop click; backdrop and hamburger have accessible names", async () => {
    setViewport(true);
    renderShell();

    await userEvent.click(menu());
    const backdrop = screen.getByRole("button", { name: "Close menu" });
    expect(backdrop).toHaveAccessibleName("Close menu");
    expect(menu()).toHaveAccessibleName("Menu");

    await userEvent.click(backdrop);

    expect(sidebar().className).not.toContain("is-open");
    expect(document.activeElement).toBe(menu());
  });

  it("inerts the closed drawer on mobile but never on desktop", async () => {
    setViewport(true);
    const { unmount } = renderShell();

    expect(sidebar().hasAttribute("inert")).toBe(true);
    expect(sidebar().getAttribute("aria-hidden")).toBe("true");

    await userEvent.click(menu());
    expect(sidebar().hasAttribute("inert")).toBe(false);
    expect(sidebar().getAttribute("aria-hidden")).toBe("false");

    unmount();

    setViewport(false);
    renderShell();
    // Desktop: docked sidebar, never inert regardless of drawer state.
    expect(sidebar().hasAttribute("inert")).toBe(false);
    expect(sidebar().getAttribute("aria-hidden")).toBe("false");
  });

  it("inerts the sidebar in Zen mode", () => {
    mockIsZen.mockReturnValue(true);
    setViewport(false);
    renderShell();

    expect(sidebar().className).toContain("is-zen");
    expect(sidebar().hasAttribute("inert")).toBe(true);
  });

  it("keeps NoteBrowser mounted across an open/close cycle", async () => {
    setViewport(true);
    renderShell();

    const search = screen.getByLabelText("note-search-stub");
    await userEvent.type(search, "graph theory");
    expect(search).toHaveValue("graph theory");

    await userEvent.click(menu());
    await userEvent.click(screen.getByRole("button", { name: "Close menu" }));

    expect(screen.getByLabelText("note-search-stub")).toHaveValue("graph theory");
  });
});

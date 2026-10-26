import type { ReactNode } from "react";
import { useEffect, useRef, useState } from "react";
import {
  createBrowserRouter,
  Link,
  Navigate,
  NavLink,
  Outlet,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { IosInstallHint } from "./components/IosInstallHint";
import { NoteBrowser } from "./components/NoteBrowser/NoteBrowser";
import { OfflineBanner } from "./components/OfflineBanner";
import { ReadOnlyBanner } from "./components/ReadOnlyBanner";
import { ReloadPrompt } from "./components/ReloadPrompt";
import { useAuth } from "./context/AuthContext";
import { NotesProvider } from "./context/NotesContext";
import { TagSelectionProvider } from "./context/TagSelectionContext";
import { useZenMode, ZenModeProvider } from "./context/ZenModeContext";
import { useFocusTrap } from "./hooks/useFocusTrap";
import { MOBILE_QUERY, useMediaQuery } from "./hooks/useMediaQuery";
import { GraphViewPage } from "./pages/GraphViewPage";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";
import { NoteViewPage } from "./pages/NoteViewPage";
import { RegisterPage } from "./pages/RegisterPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TasksPage } from "./pages/TasksPage";

/** Gates its children behind `isAuthenticated`, redirecting to `/login`
 * otherwise -- the idiomatic react-router-dom v7 pattern for a protected
 * route. Rendering the note/graph/settings shell only inside this wrapper
 * also means `NotesProvider` (nested inside, below) never mounts -- and so
 * never fires its mount-time `listNotes()` call -- for an unauthenticated
 * visitor, avoiding a console-error storm of 401s on first load. */
function RequireAuth({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

export function AppShell() {
  const { logout } = useAuth();
  const { isZen } = useZenMode();
  const isMobile = useMediaQuery(MOBILE_QUERY);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const drawerRef = useRef<HTMLElement>(null);
  const hamburgerRef = useRef<HTMLButtonElement>(null);
  const location = useLocation();

  // Navigating (a nav link, a note, the graph) closes an open drawer. The
  // body reads no dependency -- it must simply re-fire whenever the path
  // changes, which is exactly the array the exhaustive-deps lint wants to
  // shrink to `[]` (that would run it once and never close on nav).
  // biome-ignore lint/correctness/useExhaustiveDependencies: must re-fire on every pathname change
  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  // Growing past the breakpoint dissolves the drawer concept: drop any
  // open state so the sidebar reverts cleanly to its docked desktop form.
  useEffect(() => {
    if (!isMobile) setDrawerOpen(false);
  }, [isMobile]);

  // Escape closes the drawer. Focus return to the hamburger is handled by
  // useFocusTrap's restore (the hamburger is focused before we open, so it
  // is the trap's captured trigger).
  useEffect(() => {
    if (!isMobile || !drawerOpen) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setDrawerOpen(false);
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [isMobile, drawerOpen]);

  useFocusTrap(drawerRef, isMobile && drawerOpen);

  // Inert the sidebar when Zen mode has collapsed it, or when it is an
  // off-canvas drawer that is currently closed -- never for a merely
  // "closed drawer" at desktop width, which would inert the docked sidebar.
  const sidebarHidden = isZen || (isMobile && !drawerOpen);
  const sidebarClass = ["app-sidebar", isZen && "is-zen", drawerOpen && "is-open"]
    .filter(Boolean)
    .join(" ");

  return (
    // Above both the sidebar and <Routes>, so the tags picked in the search
    // box and on the front page are one selection that survives navigation.
    <TagSelectionProvider>
      <div className="app-layout">
        {/* Mobile-only chrome (index.css hides it at desktop widths). The
          wordmark lives here on mobile; the drawer keeps nav + browser +
          Log out only. */}
        <header className="app-topbar">
          <button
            type="button"
            ref={hamburgerRef}
            className="app-hamburger"
            aria-label="Menu"
            aria-expanded={drawerOpen}
            aria-controls="app-sidebar"
            onClick={() => {
              // Focus first so the trap captures the hamburger as its
              // restore target on open, and so a pointer toggle-to-close
              // still lands focus somewhere sane.
              hamburgerRef.current?.focus();
              setDrawerOpen((open) => !open);
            }}
          >
            <span aria-hidden="true">☰</span>
          </button>
          <Link to="/" className="app-topbar-brand">
            Cerebrum
          </Link>
        </header>

        {drawerOpen && (
          <button
            type="button"
            className="drawer-backdrop"
            aria-label="Close menu"
            onClick={() => setDrawerOpen(false)}
          />
        )}

        {/* Zen mode only collapses the sidebar visually (width/opacity in
          index.css) -- without `inert`/`aria-hidden`, every nav link,
          search box, tag filter, note, and Logout stays keyboard- and
          screen-reader-reachable while invisible. `inert` (React 19) drops
          it from both the tab order and the accessibility tree; `aria-
          hidden` covers browsers where `inert` isn't yet respected by
          assistive tech. The same treatment applies to the closed drawer
          on mobile. */}
        <aside
          id="app-sidebar"
          ref={drawerRef}
          className={sidebarClass}
          inert={sidebarHidden}
          aria-hidden={sidebarHidden}
        >
          <h1 className="app-title">
            <Link to="/">Cerebrum</Link>
          </h1>
          <nav className="app-nav">
            {/* `end`, or every route would mark Home active. The front page
              keeps the tags picked there, so this is the way back to them. */}
            <NavLink
              to="/"
              end
              className={({ isActive }) => (isActive ? "is-active" : undefined)}
            >
              Home
            </NavLink>
            <NavLink
              to="/graph"
              className={({ isActive }) => (isActive ? "is-active" : undefined)}
            >
              Graph
            </NavLink>
            <NavLink
              to="/tasks"
              className={({ isActive }) => (isActive ? "is-active" : undefined)}
            >
              Tasks
            </NavLink>
            <NavLink
              to="/settings"
              className={({ isActive }) => (isActive ? "is-active" : undefined)}
            >
              Settings
            </NavLink>
          </nav>
          <NoteBrowser />
          <button type="button" className="btn btn-block" onClick={logout}>
            Log out
          </button>
        </aside>
        <main className="app-main" inert={isMobile && drawerOpen}>
          <OfflineBanner />
          <ReadOnlyBanner />
          <IosInstallHint />
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/notes/*" element={<NoteViewPage />} />
            <Route path="/graph" element={<GraphViewPage />} />
            <Route path="/tasks" element={<TasksPage />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </main>
      </div>
    </TagSelectionProvider>
  );
}

/** Pathless root layout: replaces `AppRoutes`'s old pre-`<Routes>` `loading`
 * gate, which has no equivalent in a data router's route tree (see KTD1).
 * Blocks rendering every route until the initial silent-refresh attempt
 * resolves one way or the other -- otherwise an unauthenticated visitor
 * would flash the authenticated shell (and its mount-time `listNotes()`
 * 401) before the redirect to `/login` kicks in.
 *
 * This gate now only fires for a genuine first-load with no session on
 * record: a browser that has logged in before seeds `loading=false` from
 * its `sessionEstablished` marker (KTD-B) and renders the cached app
 * immediately, with `AuthProvider`'s mount effect reconciling in the
 * background. */
export function RootLayout() {
  const { loading } = useAuth();
  return (
    <>
      {/* Above the auth gate on purpose: registering the service worker
          (ReloadPrompt owns the single `useRegisterSW`) must not depend on
          being logged in, or a logged-out visit stops precaching the
          offline shell. The toast still renders inside the themed tree. */}
      <ReloadPrompt />
      {loading ? <p className="loading-indicator">Loading...</p> : <Outlet />}
    </>
  );
}

export const router = createBrowserRouter([
  {
    element: <RootLayout />,
    children: [
      { path: "/login", element: <LoginPage /> },
      { path: "/register", element: <RegisterPage /> },
      {
        path: "/*",
        element: (
          <RequireAuth>
            <NotesProvider>
              <ZenModeProvider>
                <AppShell />
              </ZenModeProvider>
            </NotesProvider>
          </RequireAuth>
        ),
      },
    ],
  },
]);

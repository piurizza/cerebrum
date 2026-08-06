import type { ReactNode } from "react";
import {
  createBrowserRouter,
  Navigate,
  NavLink,
  Outlet,
  Route,
  Routes,
} from "react-router-dom";
import { NoteBrowser } from "./components/NoteBrowser/NoteBrowser";
import { useAuth } from "./context/AuthContext";
import { NotesProvider } from "./context/NotesContext";
import { useZenMode, ZenModeProvider } from "./context/ZenModeContext";
import { GraphViewPage } from "./pages/GraphViewPage";
import { LoginPage } from "./pages/LoginPage";
import { NoteViewPage } from "./pages/NoteViewPage";
import { RegisterPage } from "./pages/RegisterPage";
import { SettingsPage } from "./pages/SettingsPage";

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

function AppShell() {
  const { logout } = useAuth();
  const { isZen } = useZenMode();
  return (
    <div className="app-layout">
      <aside className={isZen ? "app-sidebar is-zen" : "app-sidebar"}>
        <h1>Cerebrum</h1>
        <nav className="app-nav">
          <NavLink
            to="/graph"
            className={({ isActive }) => (isActive ? "is-active" : undefined)}
          >
            Graph
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
      <main className="app-main">
        <Routes>
          <Route
            path="/"
            element={
              <p className="empty-hint">
                Select a note from the sidebar, or create a new one.
              </p>
            }
          />
          <Route path="/notes/*" element={<NoteViewPage />} />
          <Route path="/graph" element={<GraphViewPage />} />
          <Route path="/settings" element={<SettingsPage />} />
        </Routes>
      </main>
    </div>
  );
}

/** Pathless root layout: replaces `AppRoutes`'s old pre-`<Routes>` `loading`
 * gate, which has no equivalent in a data router's route tree (see KTD1).
 * Blocks rendering every route until the initial silent-refresh attempt
 * resolves one way or the other -- otherwise an unauthenticated visitor
 * would flash the authenticated shell (and its mount-time `listNotes()`
 * 401) before the redirect to `/login` kicks in. */
function RootLayout() {
  const { loading } = useAuth();
  if (loading) {
    return <p className="loading-indicator">Loading...</p>;
  }
  return <Outlet />;
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

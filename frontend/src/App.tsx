import type { ReactNode } from "react";
import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import { NoteBrowser } from "./components/NoteBrowser/NoteBrowser";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { NotesProvider } from "./context/NotesContext";
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
  return (
    <div className="app-layout">
      <aside className="app-sidebar">
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

function AppRoutes() {
  const { loading } = useAuth();

  // Renders nothing (well, a minimal hint) until the initial silent-refresh
  // attempt resolves one way or the other -- otherwise an unauthenticated
  // visitor would flash the authenticated shell (and its mount-time
  // `listNotes()` 401) before the redirect to `/login` kicks in.
  if (loading) {
    return <p className="empty-hint">Loading...</p>;
  }

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route
        path="/*"
        element={
          <RequireAuth>
            <NotesProvider>
              <AppShell />
            </NotesProvider>
          </RequireAuth>
        }
      />
    </Routes>
  );
}

function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  );
}

export default App;

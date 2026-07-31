import { NavLink, Route, Routes } from "react-router-dom";
import { NoteBrowser } from "./components/NoteBrowser/NoteBrowser";
import { GraphViewPage } from "./pages/GraphViewPage";
import { NoteViewPage } from "./pages/NoteViewPage";

function App() {
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
        </nav>
        <NoteBrowser />
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
        </Routes>
      </main>
    </div>
  );
}

export default App;

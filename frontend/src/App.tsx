import { NavLink, Route, Routes } from "react-router-dom";
import { NoteBrowser } from "./components/NoteBrowser/NoteBrowser";
import { GraphViewPage } from "./pages/GraphViewPage";
import { NoteViewPage } from "./pages/NoteViewPage";

function App() {
  return (
    <div className="app-layout">
      <aside className="app-sidebar">
        <h1>Cerebrum</h1>
        <nav>
          <NavLink to="/graph">Graph</NavLink>
        </nav>
        <NoteBrowser />
      </aside>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<p>Select a note from the sidebar.</p>} />
          <Route path="/notes/*" element={<NoteViewPage />} />
          <Route path="/graph" element={<GraphViewPage />} />
        </Routes>
      </main>
    </div>
  );
}

export default App;

import { registerSW } from "virtual:pwa-register";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { router } from "./App.tsx";
import { AuthProvider } from "./context/AuthContext";
import { ThemeProvider } from "./context/ThemeContext";
import "./index.css";

// Registers the service worker that precaches the app shell (HTML/JS/CSS)
// so a later reload with no network still has something to render instead
// of the browser's own offline error page. `registerSW` no-ops safely in
// dev (no build output to precache) and in insecure contexts where service
// workers can't register at all. `autoUpdate` in vite.config.ts keeps the
// cached shell fresh on subsequent visits without a user-facing prompt.
registerSW({ immediate: true });

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element not found");
}

createRoot(rootElement).render(
  <StrictMode>
    <ThemeProvider>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </ThemeProvider>
  </StrictMode>,
);

import { registerSW } from "virtual:pwa-register";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { router } from "./App.tsx";
import { AuthProvider } from "./context/AuthContext";
import { OfflineProvider } from "./context/OfflineContext";
import { ThemeProvider } from "./context/ThemeContext";
import "./index.css";
import { syncVault } from "./offline/sync";

// Registers the service worker that precaches the app shell (HTML/JS/CSS)
// so a later reload with no network still has something to render instead
// of the browser's own offline error page. `registerSW` no-ops safely in
// dev (no build output to precache) and in insecure contexts where service
// workers can't register at all. `autoUpdate` in vite.config.ts keeps the
// cached shell fresh on subsequent visits without a user-facing prompt.
registerSW({ immediate: true });

// Proactively caches the *entire* vault -- not just notes the user opens
// -- while there's a live connection, so a later connection loss can show
// the complete last-synced vault instead of an error screen (R1). Fired
// once here, on successful load, not on a timer (KTD3 -- confirmed
// out-of-scope for this feature): this covers both a fresh desktop-app
// launch and a browser reload, which is every point this app "loads".
// Fire-and-forget -- `syncVault()` never throws (see its own docstring)
// and must not delay the initial render below. Gated on `navigator.onLine`
// since there's no point racing a sync against a connection that's
// already known to be down; `syncVault()`'s own per-note failures handle
// the rarer case of going offline *during* the sync.
if (navigator.onLine) {
  void syncVault();
}

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element not found");
}

createRoot(rootElement).render(
  <StrictMode>
    <ThemeProvider>
      <OfflineProvider>
        <AuthProvider>
          <RouterProvider router={router} />
        </AuthProvider>
      </OfflineProvider>
    </ThemeProvider>
  </StrictMode>,
);

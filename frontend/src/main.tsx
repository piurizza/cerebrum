import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { router } from "./App.tsx";
import { AuthProvider } from "./context/AuthContext";
import { OfflineProvider } from "./context/OfflineContext";
import { ThemeProvider } from "./context/ThemeContext";
import "./index.css";
import { loadVaultSettings } from "./lib/vaultSettings";
import { syncVault } from "./offline/sync";

// The service worker is now registered by `ReloadPrompt` (mounted in
// RootLayout) via `useRegisterSW` -- `registerType: "prompt"` needs a
// single `virtual:pwa-register` consumer that also owns the update toast,
// so the standalone `registerSW()` call that used to live here was removed
// (U8 / R14). Registration still happens on first render, unconditionally
// and above the auth gate.

// Proactively caches the *entire* vault -- not just notes the user opens
// -- while there's a live connection, so a later connection loss can show
// the complete last-synced vault instead of an error screen (R1). Fired
// once here, on successful load, not on a timer (KTD3 -- confirmed
// out-of-scope for this feature): this covers both a fresh desktop-app
// launch and a browser reload, which is every point this app "loads".
// Fire-and-forget -- `syncVault()` never throws (see its own docstring)
// and must not delay the initial render below.
//
// This module-load call alone never authenticates -- there's no access
// token yet on a fresh /login page load, so it 401s and gives up
// harmlessly. `AuthContext.login()` fires it again on a successful login
// for exactly that reason (2026-09-08 fix): without that second call, a
// fresh login-then-browse-then-offline session had nothing proactively
// cached, only whichever individual notes were opportunistically cached
// by ordinary navigation. This call still matters on its own for a
// reload while already authenticated (a valid refresh-token cookie makes
// its internal 401-retry succeed).
//
// Deliberately UNCONDITIONAL, not gated on `navigator.onLine` -- an
// earlier version checked it here as a "why race a sync we already know
// is doomed" optimization, but `navigator.onLine` is read at module-load
// time, before the very first paint, and real WebKitGTK testing (the
// Tauri desktop app) showed it can still report stale/inaccurate state
// this early -- silently skipping the sync for the entire session even
// though the app is genuinely online a moment later, with nothing to
// retry it. `syncVault()`'s own `listNotes()` failure handling already
// covers the case where this call turns out to be genuinely offline --
// a fast, harmless failed fetch, not a real cost worth an early-exit
// optimization that can silently disable the feature.
void syncVault();
// The server's vault folder settings (lib/vaultSettings.ts) load the same
// way, for the same reasons: fire-and-forget, never throws, re-fired by
// `AuthContext.login()`, and harmlessly 401s on a fresh /login load.
void loadVaultSettings();

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

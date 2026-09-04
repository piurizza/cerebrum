import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
// `defineConfig` comes from "vitest/config", not "vite" -- it re-exports
// Vite's own defineConfig merged with Vitest's `test` typing. Vite's plain
// `UserConfig` type has no `test` property, so importing from "vite" here
// would fail `tsc -b` (and therefore `npm run build`, since
// tsconfig.node.json includes this file in its build graph) the moment a
// `test` block is added below.
import { configDefaults, defineConfig } from "vitest/config";

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    // App-shell precaching + PWA installability. A service worker is the
    // only thing that can intercept the webview's request for the app's own
    // HTML/JS/CSS when the configured server is unreachable and answer from
    // the Cache API instead; the manifest below makes the app installable
    // to a phone's home screen (over a browser-trusted origin -- see the
    // README "Install on a phone" section).
    VitePWA({
      // `prompt`, not `autoUpdate` (KTD7): a waiting SW surfaces a Reload
      // toast (ReloadPrompt, U8) instead of silently skip-waiting and
      // reloading, which could drop an unsaved edit. `autoUpdate` also
      // never fires `needRefresh`. `injectRegister: "auto"` lets the
      // plugin wire registration through the single `useRegisterSW`
      // consumer in ReloadPrompt (the literal `false` also failed the
      // plugin's `== null` guard, so skip-waiting never engaged anyway).
      registerType: "prompt",
      injectRegister: "auto",
      // KTD9: static manifest colours cannot track the runtime theme
      // toggle, so both pin to the dark palette (which matches the app
      // icon). `<meta name="theme-color">` carries the light/dark pair and
      // is JS-updated for the toggle case (U7). `background_color` is the
      // splash colour and accepts a one-frame mismatch on the light theme.
      manifest: {
        name: "Cerebrum",
        short_name: "Cerebrum",
        id: "/",
        description:
          "A self-hosted second brain: plain-markdown notes with a graph view.",
        display: "standalone",
        start_url: "/",
        scope: "/",
        orientation: "any",
        theme_color: "#26221d",
        background_color: "#26221d",
        icons: [
          {
            src: "pwa-192x192.png",
            sizes: "192x192",
            type: "image/png",
            purpose: "any",
          },
          {
            src: "pwa-512x512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "any",
          },
          {
            src: "maskable-icon-512x512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
      workbox: {
        // Covers the built JS/CSS/HTML plus bundled font/image assets
        // (`png,ico` so the icons precache -- R9); `dist` is Vite's build
        // output root at the time workbox scans it.
        globPatterns: ["**/*.{js,css,html,svg,png,ico,woff,woff2,ttf,eot}"],
        // The SPA navigation fallback serves index.html for unknown routes;
        // exclude `/api/*` so an offline API request fails (and hits the
        // NetworkFirst rules below) instead of resolving to the app shell.
        navigateFallback: "index.html",
        navigateFallbackDenylist: [/^\/api\//],
        // Full-vault offline snapshot (R1): every note-list/note-content/
        // graph GET response the app makes -- both the ones `sync.ts`'s
        // proactive full-vault sync fires on a successful load and the
        // ordinary ones normal navigation triggers -- gets cached here as
        // a side effect of succeeding, so a later connection loss can
        // serve the whole last-synced vault, not just app-shell assets.
        //
        // `NetworkFirst`, not `CacheFirst` or `StaleWhileRevalidate`: a
        // live connection must always win when one is available (viewing
        // a note online should never show a stale cached copy over a
        // fresh one), and the cache is a fallback strictly for when the
        // network fails.
        //
        // `networkTimeoutSeconds: 4` (KTD4) matters specifically for the
        // "hanging, not refusing" case -- a dropped wifi connection or a
        // firewall that silently swallows packets doesn't fail fast the
        // way a refused connection does, and Workbox's `NetworkFirst`
        // waits indefinitely for the network by default. Without this,
        // that scenario would leave the offline UI (U4) stalled with no
        // signal for an unbounded time instead of falling back to the
        // cached snapshot within a few seconds.
        //
        // Matched with a function, not a plain `RegExp`/string `urlPattern`,
        // because `VITE_API_BASE_URL` can point the app at a different
        // origin than the one serving the built assets (e.g. the desktop
        // app) -- matching on `url.pathname` alone works regardless of
        // origin, whereas a `RegExp` tested against the full URL would
        // silently stop matching the moment the origin isn't the SW's own.
        runtimeCaching: [
          {
            // Covers both `listNotes()` (`GET /api/notes`) and
            // `getNote(path)` (`GET /api/notes/<path>`, `path` possibly
            // containing further encoded `/`s for nested folders).
            urlPattern: ({ url, request }) =>
              request.method === "GET" && /^\/api\/notes(\/.*)?$/.test(url.pathname),
            handler: "NetworkFirst",
            options: {
              cacheName: "api-notes",
              networkTimeoutSeconds: 4,
            },
          },
          {
            urlPattern: ({ url, request }) =>
              request.method === "GET" && url.pathname === "/api/graph",
            handler: "NetworkFirst",
            options: {
              cacheName: "api-graph",
              networkTimeoutSeconds: 4,
            },
          },
        ],
      },
    }),
  ],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  // `vite preview` serves the production build for the local-only Playwright
  // mobile suite; proxy its API calls to the running Docker frontend (nginx
  // -> backend) so a locally-built `dist/` can be exercised end-to-end
  // without rebuilding the frontend image.
  preview: {
    proxy: {
      "/api": {
        target: process.env.E2E_API_TARGET ?? "http://localhost:8080",
        changeOrigin: true,
      },
    },
  },
  test: {
    // Most tests render components or touch the DOM and need jsdom.
    // Pure-logic files that don't (src/lib/*.test.ts) opt out with a
    // `// @vitest-environment node` docblock instead, to skip jsdom's
    // window/document bootstrap cost where it buys nothing.
    environment: "jsdom",
    globals: false,
    setupFiles: ["./src/test/setup.ts"],
    // `e2e/` holds Playwright specs (`*.spec.ts` importing `@playwright/test`),
    // a different runner entirely -- keep Vitest from collecting them.
    exclude: [...configDefaults.exclude, "e2e/**"],
  },
});

import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
// `defineConfig` comes from "vitest/config", not "vite" -- it re-exports
// Vite's own defineConfig merged with Vitest's `test` typing. Vite's plain
// `UserConfig` type has no `test` property, so importing from "vite" here
// would fail `tsc -b` (and therefore `npm run build`, since
// tsconfig.node.json includes this file in its build graph) the moment a
// `test` block is added below.
import { defineConfig } from "vitest/config";

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    // App-shell precaching: when the configured server is unreachable, the
    // webview's request for the frontend's own HTML/JS/CSS would otherwise
    // fail outright and no app code would ever run to serve a fallback.
    // A service worker is the only thing that can intercept that request
    // and answer from the Cache API instead. Only the shell is precached
    // here -- API responses (the vault's actual content) are a later unit.
    VitePWA({
      registerType: "autoUpdate",
      injectRegister: false,
      // This unit only needs app-shell precaching (see workbox config
      // below), not full PWA installability -- skip generating/injecting
      // a web manifest so we don't ship placeholder app metadata
      // ("frontend", default theme color) nobody asked for.
      manifest: false,
      workbox: {
        // Covers the built JS/CSS/HTML plus any bundled font/image assets;
        // `dist` is Vite's build output root at the time workbox scans it.
        globPatterns: ["**/*.{js,css,html,svg,woff,woff2,ttf,eot}"],
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
  test: {
    // Most tests render components or touch the DOM and need jsdom.
    // Pure-logic files that don't (src/lib/*.test.ts) opt out with a
    // `// @vitest-environment node` docblock instead, to skip jsdom's
    // window/document bootstrap cost where it buys nothing.
    environment: "jsdom",
    globals: false,
    setupFiles: ["./src/test/setup.ts"],
  },
});

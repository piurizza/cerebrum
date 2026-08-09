import react from "@vitejs/plugin-react";
// `defineConfig` comes from "vitest/config", not "vite" -- it re-exports
// Vite's own defineConfig merged with Vitest's `test` typing. Vite's plain
// `UserConfig` type has no `test` property, so importing from "vite" here
// would fail `tsc -b` (and therefore `npm run build`, since
// tsconfig.node.json includes this file in its build graph) the moment a
// `test` block is added below.
import { defineConfig } from "vitest/config";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
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

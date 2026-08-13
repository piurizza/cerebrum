// `defineConfig` comes from "vitest/config", not "vite" -- see frontend's
// vite.config.ts for why (Vite's plain UserConfig type has no `test`
// property, which would fail `tsc` the moment a `test` block is added).
import { defineConfig } from "vitest/config";

// @ts-expect-error process is a nodejs global
const host = process.env.TAURI_DEV_HOST;

// https://vite.dev/config/
export default defineConfig(async () => ({
  // Vite options tailored for Tauri development and only applied in `tauri dev` or `tauri build`
  //
  // 1. prevent Vite from obscuring rust errors
  clearScreen: false,
  // 2. tauri expects a fixed port, fail if that port is not available
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host
      ? {
          protocol: "ws",
          host,
          port: 1421,
        }
      : undefined,
    watch: {
      // 3. tell Vite to ignore watching `src-tauri`
      ignored: ["**/src-tauri/**"],
    },
  },
  test: {
    // Most tests here are pure logic (store/health/validation) and don't
    // need jsdom -- they opt out with a `// @vitest-environment node`
    // docblock, mirroring frontend's convention. main.test.ts renders into
    // a real DOM, so it needs jsdom as the file-level default.
    environment: "jsdom",
    globals: false,
  },
}));

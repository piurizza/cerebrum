import { fetch } from "@tauri-apps/plugin-http";

// Tauri's HTTP plugin issues this request from the Rust side (reqwest),
// so it is never subject to the webview's CORS policy -- a browser
// fetch() here would be a genuinely cross-origin call to the arbitrary
// configured server and get blocked by the backend's default CORS
// allowlist. See docs/plans/2026-08-12-001-feat-desktop-app-plan.md KTD8.
const HEALTH_CHECK_TIMEOUT_MS = 5000;

export type HealthCheckResult = { ok: true } | { ok: false; reason: string };

export async function checkHealth(serverUrl: string): Promise<HealthCheckResult> {
  const healthUrl = new URL("/api/health", serverUrl).toString();
  try {
    const response = await fetch(healthUrl, {
      method: "GET",
      connectTimeout: HEALTH_CHECK_TIMEOUT_MS,
      signal: AbortSignal.timeout(HEALTH_CHECK_TIMEOUT_MS),
    });
    if (!response.ok) {
      return { ok: false, reason: `Server responded with ${response.status}` };
    }
    return { ok: true };
  } catch (err) {
    return { ok: false, reason: err instanceof Error ? err.message : "Unknown error" };
  }
}

import { fetch } from "@tauri-apps/plugin-http";

// Tauri's HTTP plugin issues this request from the Rust side (reqwest),
// so it is never subject to the webview's CORS policy -- a browser
// fetch() here would be a genuinely cross-origin call to the arbitrary
// configured server and get blocked by the backend's default CORS
// allowlist. See docs/plans/2026-08-12-001-feat-desktop-app-plan.md KTD8.
const HEALTH_CHECK_TIMEOUT_MS = 5000;

export type HealthCheckResult = { ok: true } | { ok: false; reason: string };

// A leading "/" in the second argument to `new URL()` resolves as an
// absolute path against the base's origin, discarding any existing path
// on `serverUrl` -- e.g. `new URL("/api/health", "https://host/cerebrum/")`
// resolves to "https://host/api/health", silently dropping "/cerebrum/".
// That breaks a server reverse-proxied under a subpath (reports
// "unreachable" even when healthy). Using a relative reference against a
// guaranteed-trailing-slash base preserves the existing path instead.
function healthCheckUrl(serverUrl: string): string {
  const base = serverUrl.endsWith("/") ? serverUrl : `${serverUrl}/`;
  return new URL("api/health", base).toString();
}

export async function checkHealth(serverUrl: string): Promise<HealthCheckResult> {
  const healthUrl = healthCheckUrl(serverUrl);
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

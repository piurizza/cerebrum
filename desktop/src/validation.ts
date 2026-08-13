export type ServerUrlValidation =
  | { ok: true; url: string }
  | { ok: false; error: string };

// U2's edge cases: reject empty input, reject anything that doesn't parse
// as a URL, and reject any scheme other than http/https -- the last rule
// is what stops a javascript:/data:/file: value from reaching health.ts's
// fetch or window.location.href navigation (a security-lens finding on
// the plan, see docs/plans/2026-08-12-001-feat-desktop-app-plan.md U2).
export function validateServerUrl(input: string): ServerUrlValidation {
  const trimmed = input.trim();
  if (!trimmed) {
    return { ok: false, error: "Enter a server URL." };
  }

  let parsed: URL;
  try {
    parsed = new URL(trimmed);
  } catch {
    return { ok: false, error: "That doesn't look like a valid URL." };
  }

  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    return { ok: false, error: "The URL must start with http:// or https://." };
  }

  return { ok: true, url: parsed.toString() };
}

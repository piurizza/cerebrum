import { LogicalSize } from "@tauri-apps/api/dpi";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { checkHealth } from "./health";
import { getStoredServerUrl, setStoredServerUrl } from "./store";
import { validateServerUrl } from "./validation";

// The bootstrap window ships chromeless and pinned to a small size (see
// tauri.conf.json) so the URL-entry/error screen reads as a compact native
// dialog. But that's the *bootstrap* window's shape, not the real app's --
// once a health-check succeeds we're about to navigate this same window
// into the full note-taking UI, which needs an actual title bar (close/
// minimize/maximize -- there is no other way to close the app once
// decorations are off) and room to resize. Restore normal window chrome
// right before navigating so the transition lands on a properly-sized,
// controllable window instead of the full app rendering inside the tiny
// undecorated bootstrap shell.
const APP_WINDOW_SIZE = new LogicalSize(1280, 800);

async function expandToAppWindow(): Promise<void> {
  const win = getCurrentWindow();
  await win.setDecorations(true);
  await win.setResizable(true);
  await win.setSize(APP_WINDOW_SIZE);
  await win.center();
}

// The bootstrap screen's state machine (see the mermaid diagram in
// docs/plans/2026-08-12-001-feat-desktop-app-plan.md's Planning Contract):
// NoURL/form -> Checking -> Navigated (one-way exit) or Error -> Checking.
type ScreenState =
  | { kind: "form"; prefill: string; error: string | null }
  | { kind: "checking"; url: string }
  | { kind: "error"; url: string; reason: string };

function escapeHtml(value: string): string {
  const div = document.createElement("div");
  div.textContent = value;
  return div.innerHTML;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : "unknown error";
}

// Testable navigation seam: tests substitute this instead of touching the
// real (jsdom-unfriendly) window.location.
export const navigation = {
  navigateTo(url: string): void {
    window.location.href = url;
  },
};

export function initApp(container: HTMLElement): void {
  let state: ScreenState = { kind: "form", prefill: "", error: null };

  function render(): void {
    if (state.kind === "form") {
      const s = state;
      // `prefill` is not always trusted, validated content -- a rejected
      // submission re-renders the form with the raw, unvalidated input the
      // user typed. Setting it via the DOM property below (not an
      // interpolated `value="..."` HTML attribute) means it's never parsed
      // as markup, so it can't break out of the attribute regardless of
      // what characters it contains -- unlike escapeHtml(), which only
      // escapes for text-node context and does not escape `"` (security
      // finding: an unescaped `"` in an attribute value lets a rejected
      // "URL" like `" onmouseover="...` inject a new attribute).
      container.innerHTML = `
        <form id="url-form">
          <label for="url-input">Server URL</label>
          <input
            id="url-input"
            type="text"
            placeholder="http://localhost:8080"
            autocomplete="off"
          />
          ${s.error ? `<p class="error" role="alert">${escapeHtml(s.error)}</p>` : ""}
          <button type="submit">Connect</button>
        </form>
      `;
      const form = container.querySelector<HTMLFormElement>("#url-form");
      const input = container.querySelector<HTMLInputElement>("#url-input");
      if (input) {
        input.value = s.prefill;
      }
      form?.addEventListener("submit", (event) => {
        event.preventDefault();
        handleSubmit(input?.value ?? "");
      });
      input?.focus();
      return;
    }

    if (state.kind === "checking") {
      const s = state;
      container.innerHTML = `
        <p role="status">Connecting to ${escapeHtml(s.url)}…</p>
      `;
      return;
    }

    // state.kind === "error"
    const s = state;
    container.innerHTML = `
      <p id="error-message" class="error" role="alert" tabindex="-1">
        Couldn't reach ${escapeHtml(s.url)}: ${escapeHtml(s.reason)}
      </p>
      <div class="actions">
        <button id="retry-button">Retry</button>
        <button id="change-url-button">Change server URL</button>
      </div>
    `;
    container
      .querySelector<HTMLButtonElement>("#retry-button")
      ?.addEventListener("click", () => runHealthCheck(s.url));
    container
      .querySelector<HTMLButtonElement>("#change-url-button")
      ?.addEventListener("click", () => {
        state = { kind: "form", prefill: s.url, error: null };
        render();
      });
    // Move focus to the error message so keyboard/screen-reader users
    // aren't left focused on the now-hidden form input (design-lens
    // finding on the plan).
    container.querySelector<HTMLElement>("#error-message")?.focus();
  }

  async function runHealthCheck(url: string): Promise<void> {
    state = { kind: "checking", url };
    render();
    const result = await checkHealth(url);
    if (result.ok) {
      // Best-effort: a stuck permission or platform quirk here shouldn't
      // strand the user on the bootstrap screen forever -- fall through to
      // navigation either way, just possibly still chromeless.
      await expandToAppWindow().catch(() => {});
      navigation.navigateTo(url);
      return;
    }
    state = { kind: "error", url, reason: result.reason };
    render();
  }

  function handleSubmit(rawInput: string): void {
    const validation = validateServerUrl(rawInput);
    if (!validation.ok) {
      state = { kind: "form", prefill: rawInput, error: validation.error };
      render();
      return;
    }
    // Transition out of the form synchronously, before the async store
    // write starts. The submit button would otherwise stay live during
    // that write, so a second click/Enter before it resolves could start
    // a second, concurrent health-check flow racing the first (julik
    // review finding) -- the retry button already avoids this because
    // runHealthCheck's own first line is synchronous.
    state = { kind: "checking", url: validation.url };
    render();
    setStoredServerUrl(validation.url)
      .then(() => runHealthCheck(validation.url))
      .catch((err) => {
        state = {
          kind: "form",
          prefill: validation.url,
          error: `Couldn't save the server URL (${errorMessage(err)}). Try again.`,
        };
        render();
      });
  }

  getStoredServerUrl()
    .then((stored) => {
      if (stored) {
        runHealthCheck(stored);
      } else {
        render();
      }
    })
    .catch((err) => {
      // Without this, a rejected read leaves `container` exactly as it
      // was at launch -- an empty <main id="app">, permanently blank,
      // since nothing else ever calls render() (reliability/correctness
      // finding). Falling back to the form lets the user just re-enter
      // the URL instead of being stuck.
      state = {
        kind: "form",
        prefill: "",
        error: `Couldn't read the saved server URL (${errorMessage(err)}). Enter it again.`,
      };
      render();
    });
}

window.addEventListener("DOMContentLoaded", () => {
  const app = document.querySelector<HTMLElement>("#app");
  if (app) {
    initApp(app);
  }
});

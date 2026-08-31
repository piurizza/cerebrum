import { LogicalSize } from "@tauri-apps/api/dpi";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { checkHealth } from "./health";
import {
  getHasConnectedSuccessfully,
  getStoredServerUrl,
  setHasConnectedSuccessfully,
  setStoredServerUrl,
} from "./store";
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

  // Shared tail for both paths that end up inside the real app: a plain
  // successful health-check, and the R4/KTD5 navigate-through-on-failure
  // path below. `extra`, when given, is awaited alongside the window-chrome
  // expansion rather than before it -- both are independent, best-effort,
  // fire-and-forget-tolerant operations, so there's no reason to make the
  // navigation wait for them sequentially.
  async function proceedIntoApp(url: string, extra?: Promise<unknown>): Promise<void> {
    await Promise.allSettled([extra ?? Promise.resolve(), expandToAppWindow()]);
    navigation.navigateTo(url);
  }

  async function runHealthCheck(url: string): Promise<void> {
    state = { kind: "checking", url };
    render();
    const result = await checkHealth(url);
    if (result.ok) {
      // Record that this URL has connected successfully at least once, so
      // a later failed health-check for it can navigate through to the
      // offline snapshot instead of hard-blocking on the error screen
      // (R4/KTD5). Fine to re-set this on every success rather than only
      // the first.
      await proceedIntoApp(
        url,
        setHasConnectedSuccessfully().catch(() => {}),
      );
      return;
    }
    // A URL that has connected successfully before still navigates through
    // on a failed health-check -- the cached frontend can serve the vault
    // as it stood at the last successful sync (R4). The hard error/retry
    // screen is reserved for a URL that has never connected: first-time
    // setup, a typo'd URL, a server that's never been reachable -- there
    // is nothing to show offline for those.
    const hasConnectedSuccessfully = await getHasConnectedSuccessfully().catch(
      () => false,
    );
    if (hasConnectedSuccessfully) {
      await proceedIntoApp(url);
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
        return;
      }
      // First launch (or a store that's been cleared): auto-connect to the
      // build-time default when one is configured (VITE_DEFAULT_SERVER_URL,
      // see .env.example), instead of making every install type in a URL
      // it's overwhelmingly likely to already know -- most deployments
      // point at exactly one server. Reuses handleSubmit rather than a
      // separate first-launch path: an invalid or unreachable default
      // falls through to the exact same validation-error/retry screens a
      // manually typed URL would hit, not a special case to keep in sync.
      const defaultUrl = import.meta.env.VITE_DEFAULT_SERVER_URL;
      if (defaultUrl) {
        handleSubmit(defaultUrl);
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

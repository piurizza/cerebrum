import { checkHealth } from "./health";
import { getStoredServerUrl, setStoredServerUrl } from "./store";
import { validateServerUrl } from "./validation";

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
      container.innerHTML = `
        <form id="url-form">
          <label for="url-input">Server URL</label>
          <input
            id="url-input"
            type="text"
            value="${escapeHtml(s.prefill)}"
            placeholder="http://localhost:8080"
            autocomplete="off"
          />
          ${s.error ? `<p class="error" role="alert">${escapeHtml(s.error)}</p>` : ""}
          <button type="submit">Connect</button>
        </form>
      `;
      const form = container.querySelector<HTMLFormElement>("#url-form");
      const input = container.querySelector<HTMLInputElement>("#url-input");
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
    setStoredServerUrl(validation.url).then(() => runHealthCheck(validation.url));
  }

  getStoredServerUrl().then((stored) => {
    if (stored) {
      runHealthCheck(stored);
    } else {
      render();
    }
  });
}

window.addEventListener("DOMContentLoaded", () => {
  const app = document.querySelector<HTMLElement>("#app");
  if (app) {
    initApp(app);
  }
});

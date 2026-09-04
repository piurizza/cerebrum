// Android/Chrome fires `beforeinstallprompt` when the app is installable;
// the page must `preventDefault()` it and stash the event to trigger the
// native install UI later from an in-app control (R17). iOS Safari never
// fires it -- that path is the separate A2HS hint (U10).

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

let deferredPrompt: BeforeInstallPromptEvent | null = null;
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    deferredPrompt = event as BeforeInstallPromptEvent;
    notify();
  });
  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    notify();
  });
}

/** True when the app is running as an installed PWA (any platform). */
export function isStandalone(): boolean {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    window.matchMedia("(display-mode: minimal-ui)").matches ||
    (navigator as unknown as { standalone?: boolean }).standalone === true
  );
}

/** True when a `beforeinstallprompt` event has been captured and not yet
 * consumed by a successful install. */
export function canInstall(): boolean {
  return deferredPrompt !== null;
}

/**
 * Trigger the browser's native install prompt. Returns the user's choice,
 * or `"unavailable"` if no event was captured. On `"dismissed"` the
 * deferred event is **kept** so the in-app button stays available for a
 * retry -- Chrome may not re-fire `beforeinstallprompt` for ~90 days after
 * a dismissal, and this button is the only Android install affordance
 * besides the README.
 */
export async function promptInstall(): Promise<
  "accepted" | "dismissed" | "unavailable"
> {
  if (!deferredPrompt) return "unavailable";
  await deferredPrompt.prompt();
  const { outcome } = await deferredPrompt.userChoice;
  if (outcome === "accepted") {
    deferredPrompt = null;
    notify();
  }
  return outcome;
}

/** React subscription: fires when `canInstall()` may have changed. */
export function subscribeInstall(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

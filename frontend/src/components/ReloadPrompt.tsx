import { useRegisterSW } from "virtual:pwa-register/react";
import { useEffect, useState, useSyncExternalStore } from "react";
import { getEditorDirty, subscribeEditorDirty } from "../lib/editorDirty";

// Check for a newer service worker roughly hourly while the tab is open, so
// a long-lived session still picks up a deploy without a manual reload.
const UPDATE_INTERVAL_MS = 60 * 60 * 1000;

/**
 * The single `virtual:pwa-register` consumer (R14). Renders a bottom toast
 * when a new SW is waiting ("A new version is available." + Reload) or on
 * first install ("Cached for offline reading." + Dismiss). `needRefresh`
 * outranks `offlineReady` -- one message, never both. Reload is disabled
 * while the note editor is dirty so `updateServiceWorker()`'s page reload
 * can't drop an unsaved buffer (R15); saving re-enables it.
 *
 * Mounted in `RootLayout`, above the auth gate -- registering the SW must
 * not depend on being logged in.
 */
export function ReloadPrompt() {
  const [registration, setRegistration] = useState<
    ServiceWorkerRegistration | undefined
  >();
  const {
    offlineReady: [offlineReady, setOfflineReady],
    needRefresh: [needRefresh, setNeedRefresh],
    updateServiceWorker,
  } = useRegisterSW({
    // `onRegisteredSW` only fires after `navigator.serviceWorker.register`
    // resolves -- always a later tick, so `setRegistration` is defined by
    // the time it runs.
    onRegisteredSW(_swUrl, swRegistration) {
      setRegistration(swRegistration ?? undefined);
    },
  });
  const editorDirty = useSyncExternalStore(
    subscribeEditorDirty,
    getEditorDirty,
    () => false,
  );

  useEffect(() => {
    if (!registration) return;
    const id = setInterval(() => {
      void registration.update();
    }, UPDATE_INTERVAL_MS);
    return () => clearInterval(id);
  }, [registration]);

  if (!needRefresh && !offlineReady) return null;

  if (needRefresh) {
    return (
      <div className="pwa-toast" role="status">
        <span>A new version is available.</span>
        {editorDirty && (
          <span className="pwa-toast-hint">Save your note to update.</span>
        )}
        <button
          type="button"
          className="btn btn-sm btn-primary"
          disabled={editorDirty}
          onClick={() => {
            void updateServiceWorker();
          }}
        >
          Reload
        </button>
      </div>
    );
  }

  return (
    <div className="pwa-toast" role="status">
      <span>Cached for offline reading.</span>
      <button
        type="button"
        className="btn btn-sm"
        onClick={() => {
          setOfflineReady(false);
          setNeedRefresh(false);
        }}
      >
        Dismiss
      </button>
    </div>
  );
}

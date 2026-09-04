import { useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { useOffline } from "../context/OfflineContext";
import { isStandalone } from "../lib/pwaInstall";

// iOS Safari never fires `beforeinstallprompt`, so the only install path is
// Share -> Add to Home Screen. This one-time hint points at it (R18) after
// the user has opened a note this session -- the concrete "first
// engagement" signal, no timers.

const HINT_KEY = "cerebrum-a2hs-hint";

function isIosSafari(): boolean {
  const ua = navigator.userAgent;
  // Safari only -- Chrome (CriOS), Firefox (FxiOS), Edge (EdgiOS) on iOS
  // have no Add-to-Home-Screen affordance to point at.
  return /iphone|ipad|ipod/i.test(ua) && !/crios|fxios|edgios/i.test(ua);
}

function readDismissed(): boolean {
  try {
    return window.localStorage.getItem(HINT_KEY) === "1";
  } catch {
    return false;
  }
}

export function IosInstallHint() {
  const location = useLocation();
  const { isOffline } = useOffline();
  const [engaged, setEngaged] = useState(false);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (location.pathname.startsWith("/notes/")) setEngaged(true);
  }, [location.pathname]);

  if (dismissed || !engaged) return null;
  if (!isIosSafari() || isStandalone() || readDismissed()) return null;
  // Overlay-stack rule (HTD): never stack under the offline banner or the
  // ReloadPrompt toast.
  if (isOffline || document.querySelector(".pwa-toast")) return null;

  const dismiss = () => {
    try {
      window.localStorage.setItem(HINT_KEY, "1");
    } catch {
      // Best-effort -- the session `dismissed` state below still hides it
      // now; it just won't stay hidden across a reload.
    }
    setDismissed(true);
  };

  return (
    <div className="ios-install-hint" role="status">
      <span>Tap Share, then Add to Home Screen.</span>
      <button type="button" className="btn btn-sm" onClick={dismiss}>
        Dismiss
      </button>
    </div>
  );
}

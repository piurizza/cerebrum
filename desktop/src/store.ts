import { load, type Store } from "@tauri-apps/plugin-store";

// tauri-plugin-store over hand-rolled appConfigDir() file I/O (KTD2) --
// idiomatic Tauri v2 mechanism for one small persisted setting.
const STORE_FILE = "settings.json";
const SERVER_URL_KEY = "serverUrl";

// Lazily opened, then cached for the process lifetime -- `load()` is async
// (it reads the file from disk on first call), so every caller awaits the
// same in-flight open rather than each racing their own.
let storePromise: Promise<Store> | null = null;

function getStore(): Promise<Store> {
  if (!storePromise) {
    storePromise = load(STORE_FILE).catch((err: unknown) => {
      // Don't cache a failed open -- a transient failure (e.g. the
      // settings directory not existing yet on first run) would
      // otherwise permanently disable persistence until the app
      // restarts, since every later call would keep awaiting this same
      // rejected promise (reliability finding).
      storePromise = null;
      throw err;
    });
  }
  return storePromise;
}

export async function getStoredServerUrl(): Promise<string | null> {
  const store = await getStore();
  const value = await store.get<string>(SERVER_URL_KEY);
  return value ?? null;
}

export async function setStoredServerUrl(url: string): Promise<void> {
  const store = await getStore();
  await store.set(SERVER_URL_KEY, url);
  // Flush to disk now rather than relying on the store's autosave --
  // the app may navigate away (KTD1's one-way exit) or the process may
  // exit shortly after a successful health-check.
  await store.save();
}

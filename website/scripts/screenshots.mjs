// Captures the documentation's screenshots from the demo stack started by
// demo_stack.sh. It refuses to capture anything unless the server holds the
// generated demo vault (its sentinel note), and it signs in only with the
// throwaway account demo_stack.sh created -- never E2E_USERNAME/PASSWORD.
//
// Usage (Node 22): node screenshots.mjs <credentials.json> <output-folder>
//
// Playwright comes from the frontend's dependencies (npm ci and
// npx playwright install chromium in frontend/).
import { mkdirSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { join } from "node:path";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium, devices } = require("playwright");

const SENTINEL = "about-this-demo-vault.md";

// One entry per image. `path` is the app route; `phone` captures at phone
// width; `readOnly` marks shots taken from a stack in read-only mode (the
// script captures only the shots matching the server it is pointed at);
// `prepare` runs before the capture.
const SHOTS = [
  {
    name: "tag-front-page",
    path: "/",
    prepare: async (page) => {
      await page.getByRole("button", { name: /^cooking \(/ }).click();
      await page.locator(".tag-result-list").waitFor();
    },
  },
  { name: "note", path: "/notes/projects/home-server.md" },
  { name: "note-with-image", path: "/notes/projects/garden-shed.md" },
  {
    name: "link-picker",
    path: "/notes/projects/backup-plan.md",
    prepare: async (page) => {
      await page.getByRole("button", { name: "Edit" }).click();
      const editor = page.locator(".cm-content");
      await editor.click();
      await page.keyboard.press("Control+End");
      await page.keyboard.type("\nSee also [[hom");
      await page.locator(".cm-tooltip-autocomplete").waitFor();
    },
  },
  { name: "daily-note", path: "/notes/daily/2026-10-26.md" },
  {
    name: "template-picker",
    path: "/notes/welcome.md",
    prepare: async (page) => {
      await page.getByRole("button", { name: "+ New note" }).click();
      await page.getByPlaceholder("note.md").fill("team-sync.md");
      await page.getByPlaceholder("note.md").press("Enter");
      await page.getByRole("group", { name: "Template" }).waitFor();
    },
  },
  {
    name: "tag-search",
    path: "/notes/welcome.md",
    prepare: async (page) => {
      await page.getByRole("combobox", { name: "Search notes" }).fill("#read");
      await page.getByRole("listbox", { name: "Tags" }).waitFor();
    },
  },
  { name: "graph", path: "/graph" },
  { name: "tasks", path: "/tasks" },
  {
    name: "tasks-done",
    path: "/tasks",
    prepare: async (page) => {
      // The demo vault dates its ticked tasks back from the day it was
      // built, so the Done tab opens on today's.
      await page.getByRole("tab", { name: "Done" }).click();
      await page.getByRole("heading", { name: "Today" }).waitFor();
    },
  },
  { name: "phone-note", path: "/notes/recipes/lentil-soup.md", phone: true },
  {
    name: "phone-drawer",
    path: "/notes/welcome.md",
    phone: true,
    prepare: openDrawer,
  },
  {
    name: "phone-offline",
    path: "/notes/welcome.md",
    phone: true,
    prepare: async (page) => {
      // The app caches the vault once it has synced; then cut the network
      // and open another note from the cache.
      await page.waitForTimeout(2000);
      await page.context().setOffline(true);
      await page.goto(`${baseUrl}/notes/garden/herbs.md`);
      await page.getByText(/offline/i).first().waitFor();
    },
    after: async (page) => page.context().setOffline(false),
  },
  { name: "read-only", path: "/notes/projects/home-server.md", readOnly: true },
];

async function openDrawer(page) {
  await page.locator("button[aria-label='Menu']").tap();
  const drawer = page.locator(".app-sidebar.is-open");
  await drawer.waitFor();
  // Let the slide-in finish, and drop the focus ring the drawer's focus
  // trap puts on its first link.
  await drawer.evaluate((el) =>
    Promise.all(el.getAnimations({ subtree: true }).map((a) => a.finished)),
  );
  await page.waitForTimeout(300);
  await page.evaluate(() => document.activeElement?.blur());
}

const [credentialsPath, outDir] = process.argv.slice(2);
if (!credentialsPath || !outDir) {
  console.error("usage: screenshots.mjs <credentials.json> <output-folder>");
  process.exit(2);
}
const {
  base_url: baseUrl,
  username,
  password,
} = JSON.parse(readFileSync(credentialsPath, "utf-8"));

async function assertDemoVault() {
  const login = await fetch(`${baseUrl}/api/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!login.ok) throw new Error(`demo login failed: ${login.status}`);
  const { access_token: token } = await login.json();
  const note = await fetch(`${baseUrl}/api/notes/${SENTINEL}`, {
    headers: { authorization: `Bearer ${token}` },
  });
  const body = note.ok ? await note.json() : null;
  if (!body?.content?.includes("demo_vault: cerebrum-docs")) {
    throw new Error("refusing to capture: this server does not hold the demo vault");
  }
  const settings = await fetch(`${baseUrl}/api/vault-settings`, {
    headers: { authorization: `Bearer ${token}` },
  });
  return (await settings.json()).read_only === true;
}

async function signIn(page) {
  await page.goto(`${baseUrl}/login`);
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Log in" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
}

const readOnly = await assertDemoVault();
const shots = SHOTS.filter((shot) => Boolean(shot.readOnly) === readOnly);
mkdirSync(outDir, { recursive: true });
const browser = await chromium.launch();
// The docs show Cerebrum's dark theme, which the app picks from the
// system's colour scheme when no theme is chosen in Settings.
const contexts = {
  desktop: await browser.newContext({
    viewport: { width: 1280, height: 800 },
    colorScheme: "dark",
  }),
  phone: await browser.newContext({
    ...devices["Pixel 7"],
    viewport: { width: 412, height: 915 },
    colorScheme: "dark",
  }),
};
const pages = {};
for (const [kind, context] of Object.entries(contexts)) {
  pages[kind] = await context.newPage();
  await signIn(pages[kind]);
}

for (const shot of shots) {
  const page = pages[shot.phone ? "phone" : "desktop"];
  await page.goto(`${baseUrl}${shot.path}`, { waitUntil: "networkidle" });
  if (shot.prepare) await shot.prepare(page);
  const file = join(outDir, `${shot.name}.webp`);
  await page.screenshot({ path: file, type: "webp", quality: 80 });
  if (shot.after) await shot.after(page);
  console.log(`wrote ${file}`);
}
await browser.close();

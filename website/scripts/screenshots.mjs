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
// width; `prepare` runs before the capture.
const SHOTS = [
  { name: "note", path: "/notes/projects/home-server.md" },
  { name: "note-with-image", path: "/notes/projects/garden-shed.md" },
  { name: "graph", path: "/graph" },
  { name: "tasks", path: "/tasks" },
  { name: "phone-note", path: "/notes/recipes/lentil-soup.md", phone: true },
  {
    name: "phone-drawer",
    path: "/notes/welcome.md",
    phone: true,
    prepare: async (page) => {
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
    },
  },
];

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
}

async function signIn(page) {
  await page.goto(`${baseUrl}/login`);
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(password);
  await page.getByRole("button", { name: "Log in" }).click();
  await page.waitForURL((url) => !url.pathname.startsWith("/login"));
}

await assertDemoVault();
mkdirSync(outDir, { recursive: true });
const browser = await chromium.launch();
const contexts = {
  desktop: await browser.newContext({ viewport: { width: 1280, height: 800 } }),
  phone: await browser.newContext({
    ...devices["Pixel 7"],
    viewport: { width: 412, height: 915 },
  }),
};
const pages = {};
for (const [kind, context] of Object.entries(contexts)) {
  pages[kind] = await context.newPage();
  await signIn(pages[kind]);
}

for (const shot of SHOTS) {
  const page = pages[shot.phone ? "phone" : "desktop"];
  await page.goto(`${baseUrl}${shot.path}`, { waitUntil: "networkidle" });
  if (shot.prepare) await shot.prepare(page);
  const file = join(outDir, `${shot.name}.webp`);
  await page.screenshot({ path: file, type: "webp", quality: 80 });
  console.log(`wrote ${file}`);
}
await browser.close();

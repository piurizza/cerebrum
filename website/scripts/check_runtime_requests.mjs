// Load every page of the built site in a real browser and fail on any
// request to another origin (R19). This is the runtime half of the privacy
// check: `check_no_third_party.py` reads the files, this watches what pages
// actually fetch, including requests made by JavaScript.
//
// Usage (Node 22): node check_runtime_requests.mjs <site-dir> <path-prefix>
// e.g. node check_runtime_requests.mjs site /cerebrum/
//
// Playwright comes from the frontend's dependencies, so run `npm ci` and
// `npx playwright install chromium` in frontend/ first.
import { createReadStream, readdirSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { createRequire } from "node:module";
import { extname, join, relative, resolve } from "node:path";

const require = createRequire(new URL("../../frontend/package.json", import.meta.url));
const { chromium } = require("playwright");

const [siteArg, prefixArg = "/"] = process.argv.slice(2);
if (!siteArg) {
  console.error("usage: check_runtime_requests.mjs <site-dir> <path-prefix>");
  process.exit(2);
}
const site = resolve(siteArg);
const prefix = prefixArg.endsWith("/") ? prefixArg : `${prefixArg}/`;

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css",
  ".js": "text/javascript",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".xml": "application/xml",
};

function htmlPages(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return htmlPages(path);
    return entry.name.endsWith(".html") ? [path] : [];
  });
}

// Serves the site under `prefix`, as GitHub Pages serves a project site.
const server = createServer((request, response) => {
  const url = new URL(request.url ?? "/", "http://localhost");
  if (!url.pathname.startsWith(prefix)) {
    response.writeHead(404).end();
    return;
  }
  let file = join(site, decodeURIComponent(url.pathname.slice(prefix.length)));
  if (file !== site && !file.startsWith(`${site}/`)) {
    response.writeHead(404).end();
    return;
  }
  try {
    if (statSync(file).isDirectory()) file = join(file, "index.html");
    statSync(file);
  } catch {
    response.writeHead(404).end();
    return;
  }
  response.writeHead(200, {
    "content-type": TYPES[extname(file)] ?? "application/octet-stream",
  });
  createReadStream(file).pipe(response);
});
await new Promise((done) => server.listen(0, "127.0.0.1", done));
const origin = `http://127.0.0.1:${server.address().port}`;

const problems = [];
const browser = await chromium.launch();
try {
  // Listening on the context, not the page, also catches requests made by
  // workers (the search index runs in one).
  const context = await browser.newContext();
  let current = "";
  context.on("request", (request) => {
    const url = request.url();
    if (url.startsWith("data:") || url.startsWith("blob:")) return;
    if (new URL(url).origin !== origin) problems.push(`${current}: requested ${url}`);
  });
  // A same-site load that fails would 404 once published too.
  context.on("response", (response) => {
    if (response.url().startsWith(origin) && response.status() >= 400) {
      problems.push(`${current}: ${response.status()} for ${response.url()}`);
    }
  });
  const page = await context.newPage();
  for (const file of htmlPages(site)) {
    const path = relative(site, file).split("\\").join("/");
    if (path === "404.html") continue; // served only for missing pages
    current = `${prefix}${path.replace(/index\.html$/, "")}`;
    try {
      await page.goto(`${origin}${current}`, {
        waitUntil: "networkidle",
        timeout: 30_000,
      });
    } catch (error) {
      problems.push(`${current}: ${error.message.split("\n")[0]}`);
    }
  }
} finally {
  await browser.close();
  server.close();
}

for (const problem of problems) console.error(problem);
if (problems.length > 0) {
  console.error(`${problems.length} problem(s) loading the site.`);
  process.exit(1);
}
console.log(`Loaded every page; no request left ${origin}.`);

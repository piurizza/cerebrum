import { expect, test } from "./fixtures";

// U4: the note editor and the graph canvas at phone width. Layout-only
// checks -- gesture / soft-keyboard behaviour needs a real device.

async function openFirstNote(page: import("@playwright/test").Page) {
  await page.goto("/");
  await expect(page.locator(".app-layout")).toBeVisible();
  await page.locator("button[aria-label='Menu']").tap();
  await page.locator(".note-link").first().tap();
  await expect(page).toHaveURL(/\/notes\//);
  await expect(page.locator(".note-view")).toBeVisible();
}

test("note view stacks the editor above full-width backlinks", async ({ page }) => {
  await openFirstNote(page);

  const direction = await page
    .locator(".note-view")
    .evaluate((el) => getComputedStyle(el).flexDirection);
  expect(direction).toBe("column");

  const [editor, backlinks, viewport] = await Promise.all([
    page.locator(".note-editor").boundingBox(),
    page.locator(".note-backlinks").boundingBox(),
    page.viewportSize(),
  ]);
  const vw = viewport?.width ?? 412;
  // Editor spans the column (minus app-main padding), backlinks sit below it.
  expect(editor?.width ?? 0).toBeGreaterThan(vw - 40);
  expect(backlinks?.width ?? 0).toBeGreaterThan(vw - 40);
  expect(backlinks?.y ?? 0).toBeGreaterThan(
    (editor?.y ?? 0) + (editor?.height ?? 0) - 1,
  );

  await page.screenshot({ path: "test-results/note-mobile.png", fullPage: true });
});

test("the editor keeps a usable height and accepts input", async ({ page }) => {
  await openFirstNote(page);

  const edit = page.getByRole("button", { name: "Edit" });
  if (await edit.count()) await edit.tap();

  const cm = page.locator(".cm-editor");
  const [box, viewport] = await Promise.all([cm.boundingBox(), page.viewportSize()]);
  expect(box?.height ?? 0).toBeGreaterThanOrEqual((viewport?.height ?? 915) * 0.5);

  await page.locator(".cm-content").tap();
  await page.keyboard.type("mobile edit check");
  await expect(page.locator(".cm-content")).toContainText("mobile edit check");
});

test("the graph canvas fills the viewport with no page scroll", async ({ page }) => {
  await page.goto("/graph");
  await expect(page.locator(".graph-view")).toBeVisible();
  await page.waitForLoadState("networkidle");

  const [box, viewport, canvas] = await Promise.all([
    page.locator(".graph-view").boundingBox(),
    page.viewportSize(),
    page.locator(".graph-view canvas").count(),
  ]);
  const vh = viewport?.height ?? 915;
  const vw = viewport?.width ?? 412;
  expect(canvas).toBeGreaterThan(0);
  expect(box?.width ?? 0).toBeGreaterThanOrEqual(vw - 1);
  // Bottom edge reaches the viewport bottom (fills the space under the bar).
  expect((box?.y ?? 0) + (box?.height ?? 0)).toBeGreaterThanOrEqual(vh - 1);

  const scroll = await page.evaluate(() => ({
    sh: document.documentElement.scrollHeight,
    ch: document.documentElement.clientHeight,
  }));
  expect(scroll.sh).toBeLessThanOrEqual(scroll.ch + 1);
});

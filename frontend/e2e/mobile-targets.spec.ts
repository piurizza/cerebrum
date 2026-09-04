import { expect, test } from "./fixtures";

// U3: modals go edge-to-edge and the listed controls reach >=44px at phone
// width. CSS-only change -- these checks measure the rendered result.

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".app-layout")).toBeVisible();
  await page.locator("button[aria-label='Menu']").tap();
  await expect(page.locator(".app-sidebar")).toHaveClass(/is-open/);
});

test("the folder-picker modal is a full-screen sheet", async ({ page }) => {
  await page.getByRole("button", { name: "+ New note" }).tap();

  const modal = page.locator(".modal");
  await expect(modal).toBeVisible();

  const [box, viewport, radius] = await Promise.all([
    modal.boundingBox(),
    page.viewportSize(),
    modal.evaluate((el) => getComputedStyle(el).borderTopLeftRadius),
  ]);
  const vw = viewport?.width ?? 412;
  const vh = viewport?.height ?? 915;
  expect(box?.x).toBeLessThanOrEqual(1);
  expect(box?.y).toBeLessThanOrEqual(1);
  expect(box?.width).toBeGreaterThanOrEqual(vw - 1);
  expect(box?.height).toBeGreaterThanOrEqual(vh - 1);
  expect(radius).toBe("0px");

  // The invisible `.modal-backdrop` close affordance sits under the
  // now-full-screen sheet; Escape / the in-modal Cancel button close it.
  await page.keyboard.press("Escape");
  await expect(modal).toHaveCount(0);
});

test("primary drawer controls meet the 44px target", async ({ page }) => {
  for (const locator of [
    page.locator(".app-nav a").first(),
    page.locator(".tag-pill").first(),
    page.locator(".note-folder").first(),
    page.getByRole("button", { name: "Log out" }),
  ]) {
    const box = await locator.boundingBox();
    expect(box, await locator.evaluate((el) => el.className)).not.toBeNull();
    expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
  }
});

test("note links in the tree meet the 44px target", async ({ page }) => {
  // The tree renders expanded, so a `.note-link` is already present.
  const link = page.locator(".note-link").first();
  await expect(link).toBeVisible();
  const box = await link.boundingBox();
  expect(box?.height ?? 0).toBeGreaterThanOrEqual(44);
});

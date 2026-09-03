import { expect, test } from "./fixtures";

// U2: below 768px the sidebar is an off-canvas drawer behind a top bar.
// The Pixel 7 project (playwright.config.ts) is 412px wide with touch.

const sidebar = ".app-sidebar";
const hamburger = () => "button[aria-label='Menu']";
const backdrop = () => "button[aria-label='Close menu']";

async function drawerLeft(page: import("@playwright/test").Page) {
  return page.locator(sidebar).evaluate((el) => el.getBoundingClientRect().left);
}

test.beforeEach(async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".app-layout")).toBeVisible();
});

test("top bar and hamburger show; drawer starts off-canvas", async ({ page }) => {
  await expect(page.locator(".app-topbar")).toBeVisible();
  const btn = page.locator(hamburger());
  await expect(btn).toBeVisible();
  await expect(btn).toHaveAttribute("aria-expanded", "false");

  // Sidebar is translated fully out of view to the left.
  expect(await drawerLeft(page)).toBeLessThan(0);
  await expect(page.locator(backdrop())).toHaveCount(0);
});

test("hamburger meets the 44px touch target", async ({ page }) => {
  const box = await page.locator(hamburger()).boundingBox();
  expect(box).not.toBeNull();
  expect(box?.width).toBeGreaterThanOrEqual(44);
  expect(box?.height).toBeGreaterThanOrEqual(44);
});

test("tapping the hamburger opens the drawer on-screen", async ({ page }) => {
  await page.locator(hamburger()).tap();

  await expect(page.locator(hamburger())).toHaveAttribute("aria-expanded", "true");
  await expect(page.locator(sidebar)).toHaveClass(/is-open/);
  await expect.poll(() => drawerLeft(page)).toBeGreaterThanOrEqual(0);
  await expect(page.locator(backdrop())).toBeVisible();

  // Still no horizontal page scroll with the drawer open.
  const overflow = await page.evaluate(() => ({
    sw: document.documentElement.scrollWidth,
    cw: document.documentElement.clientWidth,
  }));
  expect(overflow.sw).toBeLessThanOrEqual(overflow.cw + 1);

  await page.screenshot({ path: "test-results/drawer-open-mobile.png" });
});

test("backdrop tap closes the drawer and restores focus", async ({ page }) => {
  await page.locator(hamburger()).tap();
  await expect(page.locator(sidebar)).toHaveClass(/is-open/);

  // Tap the exposed strip of the backdrop to the right of the ~320px
  // drawer -- the element's centre sits under the drawer, which would
  // intercept the tap.
  await page.locator(backdrop()).tap({ position: { x: 390, y: 450 } });

  await expect(page.locator(sidebar)).not.toHaveClass(/is-open/);
  await expect.poll(() => drawerLeft(page)).toBeLessThan(0);
  await expect(page.locator(hamburger())).toBeFocused();
});

test("Escape closes the drawer", async ({ page }) => {
  await page.locator(hamburger()).tap();
  await expect(page.locator(sidebar)).toHaveClass(/is-open/);

  await page.keyboard.press("Escape");

  await expect(page.locator(sidebar)).not.toHaveClass(/is-open/);
  await expect(page.locator(hamburger())).toBeFocused();
});

test("a nav link navigates and closes the drawer", async ({ page }) => {
  await page.locator(hamburger()).tap();
  await page.getByRole("link", { name: "Graph" }).tap();

  await expect(page).toHaveURL(/\/graph$/);
  await expect(page.locator(sidebar)).not.toHaveClass(/is-open/);
});

test("content behind the open drawer is inert", async ({ page }) => {
  await page.locator(hamburger()).tap();
  await expect(page.locator(".app-main")).toHaveAttribute("inert", "");
});

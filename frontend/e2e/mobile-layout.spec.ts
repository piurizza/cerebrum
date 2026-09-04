import { expect, test } from "./fixtures";

// Baseline mobile-viewport checks that hold regardless of the drawer work.
// As U2-U4 land, the drawer / tap-target / modal specs go in their own
// files alongside this one.

const ROUTES = ["/", "/graph", "/tasks", "/settings"] as const;

for (const route of ROUTES) {
  test(`no horizontal scroll at phone width: ${route}`, async ({ page }) => {
    await page.goto(route);
    await expect(page.locator(".app-layout")).toBeVisible();
    // Let layout settle (fonts, force-graph canvas sizing).
    await page.waitForLoadState("networkidle");

    const overflow = await page.evaluate(() => {
      const el = document.documentElement;
      return { scrollWidth: el.scrollWidth, clientWidth: el.clientWidth };
    });

    // 1px slack for sub-pixel rounding on the DPR-scaled viewport.
    expect(overflow.scrollWidth).toBeLessThanOrEqual(overflow.clientWidth + 1);
  });
}

test("captures the authenticated landing screen", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".app-layout")).toBeVisible();
  await page.waitForLoadState("networkidle");
  await page.screenshot({
    path: "test-results/landing-mobile.png",
    fullPage: true,
  });
});

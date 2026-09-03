import { test as base, expect } from "@playwright/test";

// The access token lives only in memory (see AuthContext), and the refresh
// cookie is single-use with reuse-detection family revocation -- so a shared
// storageState file can't be replayed across parallel tests without the
// second use tripping revocation. Cheapest robust approach: log in through
// the real form once per test. Login is ~1s and this is a local-only suite.

const USERNAME = process.env.E2E_USERNAME ?? "piurizza";
const PASSWORD = process.env.E2E_PASSWORD ?? "provaprova123";

export const test = base.extend({
  page: async ({ page }, use) => {
    await page.goto("/login");
    await page.getByLabel("Username").fill(USERNAME);
    await page.getByLabel("Password").fill(PASSWORD);
    await page.getByRole("button", { name: "Log in" }).click();
    await expect(page).toHaveURL(/\/(notes)?$/, { timeout: 10_000 });
    await use(page);
  },
});

export { expect };

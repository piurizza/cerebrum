import { test as base, expect } from "@playwright/test";

// The access token lives only in memory (see AuthContext), and the refresh
// cookie is single-use with reuse-detection family revocation -- so a shared
// storageState file can't be replayed across parallel tests without the
// second use tripping revocation. Cheapest robust approach: log in through
// the real form once per test. Login is ~1s and this is a local-only suite.

// Read from the environment, never hardcoded: the suite logs in to a real
// running deployment, so a default here would publish that account's
// password with the repo.
const USERNAME = process.env.E2E_USERNAME;
const PASSWORD = process.env.E2E_PASSWORD;
if (!USERNAME || !PASSWORD) {
  throw new Error(
    "Set E2E_USERNAME and E2E_PASSWORD to an account on the running stack before `npm run test:e2e`.",
  );
}

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

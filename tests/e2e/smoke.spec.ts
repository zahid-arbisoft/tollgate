import { expect, test } from "@playwright/test";

// UI smoke: dashboard login → create key → see it listed.
// Preconditions: a server with seeded data; token via env.
//   cd tests/e2e && npm install && npx playwright install chromium
//   TOLLGATE_E2E_TOKEN=$(uv run tollgate key admin-token) npm run smoke
const TOKEN = process.env.TOLLGATE_E2E_TOKEN ?? "";

test("healthz", async ({ request }) => {
  const resp = await request.get("/healthz");
  expect(resp.ok()).toBeTruthy();
  expect((await resp.json()).status).toBe("ok");
});

test("dashboard login and key creation", async ({ page }) => {
  await page.goto("/");
  await page.getByPlaceholder("admin token").fill(TOKEN);
  await page.getByRole("button", { name: /unlock dashboard/i }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();

  await page.getByRole("link", { name: "Keys" }).click();
  await page.getByRole("button", { name: /create key/i }).first().click();
  await page.getByPlaceholder("my-project").fill("e2e-smoke");
  await page.getByRole("button", { name: /next: limits/i }).click();
  // .last(): the wizard's button (the header "Create key" still matches).
  await page.getByRole("button", { name: /create key/i }).last().click();
  await expect(page.getByText(/shown once/i)).toBeVisible();
  // The freshly created key renders inside the modal's code block.
  await expect(page.locator("div.fixed code")).toContainText("tg-");
});

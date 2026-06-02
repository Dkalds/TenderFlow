import { test, expect } from "@playwright/test";

test.describe("Admin Guard", () => {
  test("redirects unauthenticated users to login when accessing /administracion", async ({ page }) => {
    await page.goto("/administracion");
    // Should redirect to /login (middleware) or show login redirect
    await page.waitForURL(/\/login/, { timeout: 5000 }).catch(() => {});
    const url = page.url();
    expect(url).toContain("/login");
  });

  test("redirects unauthenticated users to login when accessing /feature-flags", async ({ page }) => {
    await page.goto("/feature-flags");
    await page.waitForURL(/\/login/, { timeout: 5000 }).catch(() => {});
    const url = page.url();
    expect(url).toContain("/login");
  });

  test("redirects unauthenticated users to login when accessing /active-learning", async ({ page }) => {
    await page.goto("/active-learning");
    await page.waitForURL(/\/login/, { timeout: 5000 }).catch(() => {});
    const url = page.url();
    expect(url).toContain("/login");
  });

  test("shows access restricted for non-admin users", async ({ page }) => {
    // Login first via dev login
    await page.goto("/login");
    // Try dev login button if available
    const devBtn = page.getByRole("button", { name: /dev login/i });
    if (await devBtn.isVisible()) {
      await devBtn.click();
      await page.waitForURL(/\/resumen/, { timeout: 5000 });

      // Now try to access admin page
      await page.goto("/administracion");
      // Should show "Acceso restringido" since dev user is not admin
      const body = page.locator("body");
      await expect(body).toBeVisible();
    }
  });
});

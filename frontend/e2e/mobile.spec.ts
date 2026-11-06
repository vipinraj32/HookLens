import path from "node:path";

import { expect, test } from "@playwright/test";

const SHOTS = process.env.E2E_SCREENSHOT_DIR;

test("mobile navigation drawer opens, navigates and dismisses", async ({ page }, info) => {
  await page.goto("/app");
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  const open = page.getByRole("button", { name: "Open navigation" });
  await expect(open).toHaveAttribute("aria-expanded", "false");
  await open.click();
  await expect(open).toHaveAttribute("aria-expanded", "true");
  if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `${info.project.name}-drawer.png`) });

  await page.keyboard.press("Escape");
  await expect(open).toHaveAttribute("aria-expanded", "false");

  await open.click();
  await page.getByRole("navigation", { name: "Mobile" }).getByRole("link", { name: "Evidence explorer" }).click();
  await page.waitForURL(/\/app\/evidence$/);
  await expect(page.getByRole("heading", { name: "Evidence", exact: true })).toBeVisible();
  await expect(open).toHaveAttribute("aria-expanded", "false");
});

import { existsSync, readFileSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

/**
 * The core HookLens workflow against the oracle-gated withdrawal fixture:
 * scan → findings + evidence → fork simulation → decoded revert → LP exposure → report (JSON + PDF).
 */
const DEPLOYMENTS = path.resolve(__dirname, "../../contracts/deployments/31337.json");
const SHOTS = process.env.E2E_SCREENSHOT_DIR;

function oracleHook(): string | null {
  if (!existsSync(DEPLOYMENTS)) return null;
  const d = JSON.parse(readFileSync(DEPLOYMENTS, "utf8")) as { hook_oracle_gated?: { address?: string } };
  return d.hook_oracle_gated?.address ?? null;
}

test("scan, simulate, measure LP exposure and export a report", async ({ page }, info) => {
  const hook = oracleHook();
  test.skip(!hook, "Deploy the fixtures first: scripts/dev-chain.sh");
  const shot = async (name: string) => {
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `${info.project.name}-${name}.png`), fullPage: true });
  };

  // ------------------------------------------------------------ scan
  await page.goto("/app/scan");
  await expect(page.getByRole("heading", { name: "Scan a Uniswap v4 hook" })).toBeVisible();

  // Client-side validation runs before anything is sent.
  await page.getByLabel("Hook address").fill("0x123");
  await page.getByLabel("Hook address").blur();
  await expect(page.getByText("Enter a 20-byte hex address starting with 0x.")).toBeVisible();

  await page.getByLabel("Hook address").fill(hook!);
  await expect(page.getByText("BEFORE_REMOVE_LIQUIDITY").first()).toBeVisible(); // local permission preview
  await shot("scan-form");
  await page.getByRole("button", { name: "Start scan" }).click();

  // Live progress, then redirect to Hook Intelligence when the job succeeds.
  await page.waitForURL(/\/app\/scans\/[0-9a-f-]+$/, { timeout: 120_000 });
  const scanUrl = page.url();
  await expect(page.getByRole("heading", { name: "OracleGatedWithdrawalHook" })).toBeVisible();
  await expect(page.getByRole("tab", { name: /Findings \(\d+\)/ })).toBeVisible();

  // ------------------------------------------------------------ findings + evidence
  const oracleFinding = page.getByRole("button", { name: /depend\(s\) on an external oracle/ });
  await expect(oracleFinding).toBeVisible();
  await oracleFinding.click();
  await expect(page.getByRole("heading", { name: /Evidence \(\d+\)/ })).toBeVisible();
  await expect(page.locator("article[id^='EV-']").first()).toBeVisible();
  // Without an API key the AI path must say so instead of inventing output.
  await page.getByRole("button", { name: "Explain this finding" }).click();
  await expect(page.getByText(/AI explanations are disabled/)).toBeVisible();
  await shot("hook-intelligence");

  await page.getByRole("tab", { name: "Permissions" }).click();
  await expect(page.getByRole("cell", { name: "BEFORE_REMOVE_LIQUIDITY" })).toBeVisible();
  await page.getByRole("tab", { name: /Pools \(1\)/ }).click();
  await expect(page.getByText("hlWETH / hlUSD").or(page.getByText("hlUSD / hlWETH"))).toBeVisible();

  // ------------------------------------------------------------ adversarial lab
  await page.goto(`${scanUrl}/lab`);
  await expect(page.getByRole("heading", { name: "Run simulation" })).toBeVisible();
  // Run only the withdrawal scenario to keep the test fast.
  const boxes = page.getByRole("group", { name: "Scenarios" }).getByRole("checkbox");
  await expect(boxes).toHaveCount(6);
  for (const box of await boxes.all()) {
    const name = (await box.evaluate((el) => el.closest("label")?.textContent ?? "")) as string;
    if (!name.startsWith("Withdrawal failure")) await box.uncheck();
  }
  await expect(page.getByRole("checkbox", { name: /^Withdrawal failure/ })).toBeChecked();
  await page.getByRole("button", { name: "Run on fork" }).click();

  const runRow = page.getByRole("row", { name: /Withdrawal failure/ });
  await expect(runRow.getByText("unexpected revert")).toBeVisible({ timeout: 300_000 });
  // The failing step is auto-selected and its revert decoded from the real trace.
  await expect(page.getByText("Decoded revert")).toBeVisible();
  await expect(page.getByText(/reverted: HookLens: mocked oracle revert/).first()).toBeVisible();
  await expect(page.getByText("Call trace")).toBeVisible();
  await expect(page.getByText(/forge test --match-contract/)).toBeVisible();
  await shot("adversarial-lab");

  // ------------------------------------------------------------ LP exposure
  await page.getByRole("link", { name: "Apply to LP position" }).click();
  await page.waitForURL(/\/app\/lp\?scan=/);
  await expect(page.getByRole("heading", { name: "What is this position exposed to?" })).toBeVisible();
  const quote = page.getByLabel("Quote prices as");
  // Quote in USD per WETH whichever token is token0.
  const options = await quote.locator("option").allTextContents();
  await quote.selectOption({ index: options.findIndex((o) => o.trim().startsWith("hlUSD per")) });
  await page.getByLabel("Lower price").fill("1500");
  await page.getByLabel("Upper price").fill("3000");
  const wethField = page.getByLabel("hlWETH amount");
  await wethField.fill("1");
  await page.getByLabel("hlUSD amount").fill("2000");
  await page.getByRole("button", { name: "Compute exposure" }).click();

  await expect(page.getByRole("heading", { name: "Baseline position" })).toBeVisible();
  await expect(page.getByText(/Withdrawal blocked under \d+ condition/)).toBeVisible();
  await expect(page.getByText("Fee income", { exact: true })).toBeVisible();
  await expect(page.getByRole("table", { name: /LP value vs hold value/ })).toBeVisible();
  await shot("lp-exposure");

  // ------------------------------------------------------------ evidence explorer
  await page.goto(`/app/evidence?scan=${scanUrl.split("/").pop()}`);
  await page.getByLabel("Kind").selectOption("source_excerpt");
  await expect(page.locator("article[id^='EV-']").first()).toBeVisible();
  await expect(page.getByText(/OracleGatedWithdrawalHook\.sol:\d+/).first()).toBeVisible();
  await shot("evidence");

  // ------------------------------------------------------------ report
  await page.goto(scanUrl);
  await page.getByRole("tab", { name: "Reports" }).click();
  await page.getByRole("button", { name: "Generate" }).click();
  const reportLink = page.getByRole("link", { name: /^Report / }).first();
  await expect(reportLink).toBeVisible();
  await reportLink.click();
  await page.waitForURL(/\/app\/reports\/[0-9a-f-]+$/);
  await expect(page.getByRole("heading", { name: /Findings \(\d+\)/ })).toBeVisible();
  const pdf = page.getByRole("link", { name: "PDF" });
  await expect(pdf).toBeVisible({ timeout: 60_000 });
  const res = await page.request.get((await pdf.getAttribute("href"))!);
  expect(res.ok()).toBeTruthy();
  expect((await res.body()).subarray(0, 4).toString()).toBe("%PDF");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "JSON" }).click();
  const json = JSON.parse(readFileSync((await (await download).path())!, "utf8")) as { report_version: string; content_hash: string };
  expect(json.report_version).toBe("1.0.0");
  expect(json.content_hash).toMatch(/^sha256:[0-9a-f]{64}$/);
  await shot("report");
});

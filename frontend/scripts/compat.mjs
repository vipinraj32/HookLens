// Usage: node scripts/compat.mjs <next|vitest> [args...]
//
// Some dependencies (@tailwindcss/node, jsdom's css-color) require() ESM-only packages.
// Node >= 22.12 allows that by default; Node 22.0-22.11 needs --experimental-require-module,
// passed via NODE_OPTIONS so worker processes (Turbopack, Vitest pools) inherit it.
// On newer Node this wrapper just runs the tool.
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

// Paths relative to node_modules (package "exports" may hide bin files from require.resolve).
const BINS = { next: "next/dist/bin/next", vitest: "vitest/vitest.mjs" };
const [tool, ...args] = process.argv.slice(2);
if (!BINS[tool]) {
  console.error(`usage: node scripts/compat.mjs <${Object.keys(BINS).join("|")}> [args...]`);
  process.exit(2);
}
const bin = fileURLToPath(new URL(`../node_modules/${BINS[tool]}`, import.meta.url));
const [major, minor] = process.versions.node.split(".").map(Number);
const env = { ...process.env };
if (major === 22 && minor < 12) {
  env.NODE_OPTIONS = `${env.NODE_OPTIONS ?? ""} --experimental-require-module --no-warnings=ExperimentalWarning`.trim();
}
const child = spawn(process.execPath, [bin, ...args], { stdio: "inherit", env });
child.on("exit", (code, signal) => (signal ? process.kill(process.pid, signal) : process.exit(code ?? 1)));

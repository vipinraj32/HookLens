import type { CSSProperties } from "react";

/**
 * Real console output of `hooklens scan ./contracts --local --fail-on high` (HookLens 0.2.0) on this
 * repository's test fixture hooks, abridged. Lines reveal one by one (CSS only, motion-safe).
 */
const LINES: { text: string; tone?: "cmd" | "dim" | "med" | "low" | "ok" }[] = [
  { text: "$ hooklens scan ./contracts --local --fail-on high", tone: "cmd" },
  { text: "[project] foundry project (scan paths: src)", tone: "dim" },
  { text: "[compile] solc 0.8.26 (cancun): 10 file(s)", tone: "dim" },
  { text: "[detect] 15 contract(s) discovered, 6 selected for analysis", tone: "dim" },
  { text: "" },
  { text: "MEDIUM  beforeRemoveLiquidity can revert liquidity removal", tone: "med" },
  { text: "  OracleGatedWithdrawalHook - contracts/src/fixtures/OracleGatedWithdrawalHook.sol:57", tone: "dim" },
  { text: "MEDIUM  beforeRemoveLiquidity depend(s) on an external oracle", tone: "med" },
  { text: "MEDIUM  Hook controls the LP fee applied to swaps", tone: "med" },
  { text: "MEDIUM  Pause mechanism gates liquidity removal", tone: "med" },
  { text: "LOW     Contract is a delegating proxy: hook logic is replaceable", tone: "low" },
  { text: "" },
  { text: "Findings: 29  (medium 8, low 10, informational 11)" },
  { text: "Gate: no findings at or above 'high'.", tone: "ok" },
];

const TONE: Record<string, string> = {
  cmd: "text-fg",
  dim: "text-faint",
  med: "text-sev-medium",
  low: "text-sev-low",
  ok: "text-ok",
};

export function Terminal() {
  return (
    <figure className="overflow-hidden rounded-xl border border-line bg-bg shadow-2xl shadow-black/40">
      <div className="flex items-center gap-1.5 border-b border-line bg-surface px-3 py-2">
        <span aria-hidden="true" className="size-2.5 rounded-full bg-line" />
        <span aria-hidden="true" className="size-2.5 rounded-full bg-line" />
        <span aria-hidden="true" className="size-2.5 rounded-full bg-line" />
        <figcaption className="ml-2 font-mono text-[11px] text-faint">hooklens — real output, abridged</figcaption>
      </div>
      <pre className="overflow-x-auto p-4 font-mono text-[12px] leading-[1.7]">
        {LINES.map((l, i) => (
          <span
            key={i}
            className={`terminal-line block ${l.tone ? TONE[l.tone] : "text-fg/90"}`}
            style={{ "--i": i } as CSSProperties}
          >
            {l.text || " "}
          </span>
        ))}
      </pre>
    </figure>
  );
}

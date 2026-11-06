"use client";

import { AlertTriangle, ArrowRight, CircleSlash, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useId, useMemo, useState } from "react";

import { cn } from "@/lib/format";

/** Uniswap v4 hook permission flags (v4-core Hooks.sol): the low 14 bits of the hook address. */
const FLAGS = [
  { bit: 13, name: "beforeInitialize", stage: "Initialize", note: "Runs once when a pool is created; can reject pool creation." },
  { bit: 12, name: "afterInitialize", stage: "Initialize", note: "Runs once after a pool is created." },
  { bit: 11, name: "beforeAddLiquidity", stage: "Add liquidity", note: "Runs before every deposit; can revert and block new liquidity." },
  { bit: 10, name: "afterAddLiquidity", stage: "Add liquidity", note: "Runs after every deposit." },
  { bit: 9, name: "beforeRemoveLiquidity", stage: "Remove liquidity", note: "Runs before every withdrawal; a revert here blocks LPs from exiting.", lp: true },
  { bit: 8, name: "afterRemoveLiquidity", stage: "Remove liquidity", note: "Runs after every withdrawal; a revert here also blocks the exit.", lp: true },
  { bit: 7, name: "beforeSwap", stage: "Swap", note: "Runs before every swap; can override the LP fee or revert swaps." },
  { bit: 6, name: "afterSwap", stage: "Swap", note: "Runs after every swap." },
  { bit: 5, name: "beforeDonate", stage: "Donate", note: "Runs before donations to the pool." },
  { bit: 4, name: "afterDonate", stage: "Donate", note: "Runs after donations to the pool." },
  { bit: 3, name: "beforeSwapReturnDelta", stage: "Return deltas", needs: 7, note: "Hook can take or add tokens in the swap amounts.", lp: true },
  { bit: 2, name: "afterSwapReturnDelta", stage: "Return deltas", needs: 6, note: "Hook can take or add tokens after the swap settles.", lp: true },
  { bit: 1, name: "afterAddLiquidityReturnDelta", stage: "Return deltas", needs: 10, note: "Hook can change what an LP pays to deposit.", lp: true },
  { bit: 0, name: "afterRemoveLiquidityReturnDelta", stage: "Return deltas", needs: 8, note: "Hook can change what an LP receives on withdrawal.", lp: true },
] as const;

const STAGES = ["Initialize", "Add liquidity", "Remove liquidity", "Swap", "Donate", "Return deltas"] as const;

/** HookLens' own local test fixtures (deterministic Anvil deployment from scripts/dev-chain.sh). */
const PRESETS = [
  { label: "Oracle-gated withdrawal", address: "0x8c555A02175966f3c564bF3f3d62E722E6D04200" },
  { label: "Dynamic fee", address: "0x09a1c8543dE6f4cD9049dFD234E84Ee3EA3Ea080" },
  { label: "Pausable (proxy)", address: "0x7ba9b70c1186A4661Ae6DAD5f568b579a5120A80" },
  { label: "Swap fee delta", address: "0xb57432655d24b4D28F961a68Ed0fCCF253870044" },
];

const ADDRESS_RE = /^0x[0-9a-fA-F]{40}$/;

export function PermissionDecoder() {
  const inputId = useId();
  const [value, setValue] = useState(PRESETS[0].address);
  const trimmed = value.trim();
  const valid = ADDRESS_RE.test(trimmed);

  const decoded = useMemo(() => {
    if (!valid) return null;
    const bits = Number.parseInt(trimmed.slice(-4), 16) & 0x3fff;
    const on = new Set(FLAGS.filter((f) => (bits >> f.bit) & 1).map((f) => f.bit));
    const invalid = FLAGS.filter((f) => "needs" in f && on.has(f.bit) && !on.has(f.needs));
    return { bits, on, invalid };
  }, [trimmed, valid]);

  const enabled = decoded ? FLAGS.filter((f) => decoded.on.has(f.bit)) : [];
  const lpRelevant = enabled.filter((f) => "lp" in f && f.lp);

  return (
    <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <div className="flex flex-col gap-4">
        <div>
          <label htmlFor={inputId} className="text-sm font-medium">
            Hook address
          </label>
          <input
            id={inputId}
            value={value}
            onChange={(e) => setValue(e.target.value)}
            spellCheck={false}
            autoComplete="off"
            placeholder="0x…"
            aria-invalid={trimmed !== "" && !valid}
            aria-describedby={`${inputId}-hint`}
            className={cn(
              "mt-2 h-11 w-full rounded-md border bg-bg px-3 font-mono text-[13px] outline-none transition-colors focus-visible:border-accent",
              trimmed !== "" && !valid ? "border-bad" : "border-line",
            )}
          />
          <p id={`${inputId}-hint`} className={cn("mt-2 text-xs", trimmed !== "" && !valid ? "text-bad" : "text-faint")}>
            {trimmed !== "" && !valid
              ? "0x followed by 40 hex characters."
              : "Decoded locally. Nothing is sent."}
          </p>
        </div>

        <div>
          <p className="text-xs text-faint">Test fixtures (local Anvil):</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {PRESETS.map((p) => (
              <button
                key={p.address}
                type="button"
                onClick={() => setValue(p.address)}
                aria-pressed={trimmed.toLowerCase() === p.address.toLowerCase()}
                className="rounded-full border border-line px-3 py-1 text-xs text-muted transition-colors hover:border-accent/60 hover:text-fg aria-pressed:border-accent aria-pressed:bg-accent/10 aria-pressed:text-fg"
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        <div aria-live="polite" className="rounded-xl border border-line bg-bg p-4 text-sm">
          {!decoded ? (
            <p className="text-muted">Paste an address to see its enabled callbacks.</p>
          ) : (
            <div className="flex flex-col gap-3">
              <p className="font-mono text-xs text-faint">
                low 14 bits = 0x{decoded.bits.toString(16).padStart(4, "0")} ={" "}
                {decoded.bits.toString(2).padStart(14, "0")}
              </p>
              {enabled.length === 0 ? (
                <p className="flex items-start gap-2 text-muted">
                  <CircleSlash aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                  No permission bits set. Never called as a hook.
                </p>
              ) : (
                <p>
                  <strong>{enabled.length}</strong> callback{enabled.length === 1 ? "" : "s"} enabled
                  {lpRelevant.length > 0 ? (
                    <>
                      , <strong className="text-warn">{lpRelevant.length}</strong>{" "}
                      {lpRelevant.length === 1 ? "affects" : "affect"} LP withdrawals or payouts.
                    </>
                  ) : (
                    "."
                  )}
                </p>
              )}
              {decoded.invalid.length > 0 ? (
                <p className="flex items-start gap-2 text-bad">
                  <AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                  Invalid set: {decoded.invalid.map((f) => f.name).join(", ")} without its base callback. Rejected at initialization.
                </p>
              ) : null}
              <p className="flex items-start gap-2 text-xs text-faint">
                <ShieldCheck aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                <span>
                  Bits show <em>which</em> callbacks run, not what they do.
                </span>
              </p>
              <Link
                href="/app/scan"
                className="inline-flex w-fit items-center gap-1.5 text-sm font-medium text-accent hover:underline"
              >
                Run a full scan <ArrowRight aria-hidden="true" className="size-4" />
              </Link>
            </div>
          )}
        </div>
      </div>

      <ul aria-label="Hook permission flags" className="grid gap-x-4 gap-y-5 sm:grid-cols-2">
        {STAGES.map((stage) => (
          <li key={stage}>
            <p className="mb-2 text-xs font-medium uppercase tracking-wide text-faint">{stage}</p>
            <ul className="flex flex-col gap-1.5">
              {FLAGS.filter((f) => f.stage === stage).map((f) => {
                const on = decoded?.on.has(f.bit) ?? false;
                return (
                  <li
                    key={f.bit}
                    title={f.note}
                    className={cn(
                      "flex items-start gap-3 rounded-lg border px-3 py-2 transition-colors duration-300",
                      on
                        ? "lp" in f && f.lp
                          ? "border-warn/50 bg-warn/10"
                          : "border-accent/50 bg-accent/10"
                        : "border-line/70 opacity-60",
                    )}
                  >
                    <span
                      aria-hidden="true"
                      className={cn(
                        "mt-1.5 size-2 shrink-0 rounded-full transition-colors duration-300",
                        on ? ("lp" in f && f.lp ? "bg-warn" : "bg-accent") : "bg-line",
                      )}
                    />
                    <span className="min-w-0">
                      <span className="flex items-baseline justify-between gap-2">
                        <span className="truncate font-mono text-[12.5px]">{f.name}</span>
                        <span className="shrink-0 whitespace-nowrap font-mono text-[11px] text-faint">
                          bit {f.bit}
                          <span className="sr-only">{on ? ", enabled" : ", disabled"}</span>
                        </span>
                      </span>
                      {on ? <span className="mt-0.5 block text-xs text-muted">{f.note}</span> : null}
                    </span>
                  </li>
                );
              })}
            </ul>
          </li>
        ))}
      </ul>
    </div>
  );
}

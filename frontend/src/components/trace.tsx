"use client";

import { ChevronRight } from "lucide-react";
import { useMemo, useState } from "react";

import type { DecodedRevertT, Trace, TraceNode } from "@/lib/api/models";
import { cn, shortHex } from "@/lib/format";

export const HOOK_CALLBACKS = new Set([
  "beforeInitialize",
  "afterInitialize",
  "beforeAddLiquidity",
  "afterAddLiquidity",
  "beforeRemoveLiquidity",
  "afterRemoveLiquidity",
  "beforeSwap",
  "afterSwap",
  "beforeDonate",
  "afterDonate",
]);

export function RevertMessage({ revert }: { revert: DecodedRevertT }) {
  const chain: DecodedRevertT[] = [];
  let cur: DecodedRevertT | null | undefined = revert;
  while (cur && chain.length < 6) {
    chain.push(cur);
    cur = cur.inner;
  }
  return (
    <div className="flex flex-col gap-1.5">
      <p className="break-words text-sm text-bad">{revert.message ?? revert.name ?? revert.kind}</p>
      <ol className="flex flex-col gap-1 text-xs">
        {chain.map((r, i) => (
          <li key={i} className="flex flex-wrap items-center gap-2" style={{ paddingLeft: i * 12 }}>
            <span className="rounded border border-line px-1 font-mono text-[10px] text-faint">{r.kind}</span>
            <span className="font-mono text-fg/80">
              {r.signature ?? r.name ?? r.message ?? "—"}
              {r.args && Object.keys(r.args).length ? (
                <span className="text-muted">
                  {" "}
                  {Object.entries(r.args)
                    .map(([k, v]) => `${k}=${String(v)}`)
                    .join(", ")}
                </span>
              ) : null}
            </span>
            {r.function ? <span className="text-faint">in {r.function.split("(")[0]}</span> : null}
            {r.selector ? <span className="font-mono text-faint">{r.selector}</span> : null}
          </li>
        ))}
        {revert.details ? (
          <li className="text-faint">
            PoolManager context: <span className="font-mono">{revert.details.signature ?? revert.details.name}</span>
          </li>
        ) : null}
      </ol>
    </div>
  );
}

function NodeRow({
  node,
  byIdx,
  depth,
  defaultOpen,
  hook,
  interesting,
}: {
  node: TraceNode;
  byIdx: Map<number, TraceNode>;
  depth: number;
  defaultOpen: boolean;
  hook?: string;
  interesting: Set<number>;
}) {
  const kids = (node.children ?? []).map((c) => byIdx.get(c)).filter((n): n is TraceNode => !!n);
  const [open, setOpen] = useState(defaultOpen || !node.success);
  const who = node.label ?? shortHex(node.address);
  const fn = node.function ? node.function.split("(")[0] : null;
  const isHook = !!hook && node.address.toLowerCase() === hook.toLowerCase();
  const isCallback = isHook && !!fn && HOOK_CALLBACKS.has(fn);
  return (
    <li>
      <div
        className={cn(
          "group flex min-w-0 items-start gap-1.5 rounded px-1 py-0.5 font-mono text-[12px] hover:bg-surface-2",
          !node.success && "bg-bad/5",
          isCallback && "bg-accent/[0.06] ring-1 ring-accent/25",
        )}
        style={{ paddingLeft: depth * 14 }}
      >
        {kids.length ? (
          <button
            type="button"
            aria-label={open ? "Collapse call" : "Expand call"}
            aria-expanded={open}
            onClick={() => setOpen(!open)}
            className="mt-0.5 shrink-0 text-faint hover:text-fg"
          >
            <ChevronRight aria-hidden="true" className={cn("size-3.5 transition-transform", open && "rotate-90")} />
          </button>
        ) : (
          <span aria-hidden="true" className="inline-block w-3.5 shrink-0" />
        )}
        <span className={cn("shrink-0 text-[10px] uppercase", node.kind === "DELEGATECALL" ? "text-warn" : "text-faint")}>
          {node.kind.toLowerCase()}
        </span>
        <span className="min-w-0 break-all">
          <span className={isHook ? "font-semibold text-fg" : "text-muted"}>{who}</span>
          <span className="text-faint">.</span>
          <span className="text-fg">{node.function ? node.function.split("(")[0] : (node.selector ?? "fallback")}</span>
          <span className="text-faint">()</span>
          {isCallback ? <span className="ml-2 rounded border border-accent/40 px-1 text-[10px] font-medium text-accent">hook callback</span> : null}
          {node.gas_used !== undefined ? <span className="ml-2 text-faint">gas {node.gas_used.toLocaleString()}</span> : null}
          {!node.success ? <span className="ml-2 text-bad">✗ {node.revert?.message ?? node.status ?? "revert"}</span> : null}
        </span>
      </div>
      {open && kids.length ? (
        <ul>
          {kids.map((k) => (
            <NodeRow key={k.idx} node={k} byIdx={byIdx} depth={depth + 1} defaultOpen={interesting.has(k.idx)} hook={hook} interesting={interesting} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

/** Decoded call tree for one harness step (cheatcode and console calls are pruned server-side). */
export function TraceTree({ trace, roots, hook }: { trace: Trace; roots: number[]; hook?: string }) {
  const byIdx = useMemo(() => new Map((trace.nodes ?? []).map((n) => [n.idx, n])), [trace.nodes]);
  // Frames whose subtree contains a hook callback; they start expanded so callbacks are visible.
  const interesting = useMemo(() => {
    const out = new Set<number>();
    const hk = hook?.toLowerCase();
    const visit = (idx: number, seen: Set<number>): boolean => {
      const n = byIdx.get(idx);
      if (!n || seen.has(idx)) return false;
      seen.add(idx);
      let hit = false;
      for (const c of n.children ?? []) if (visit(c, seen)) hit = true;
      const self = !!hk && n.address.toLowerCase() === hk && HOOK_CALLBACKS.has((n.function ?? "").split("(")[0]);
      if (hit) out.add(idx);
      return hit || self;
    };
    const seen = new Set<number>();
    for (const r of roots) visit(r, seen);
    return out;
  }, [byIdx, roots, hook]);
  const nodes = roots.map((r) => byIdx.get(r)).filter((n): n is TraceNode => !!n);
  if (!nodes.length) return <p className="text-xs text-faint">No trace nodes were attributed to this step.</p>;
  return (
    <ul className="max-h-[28rem] overflow-auto rounded-lg border border-line bg-bg p-2">
      {nodes.map((n) => (
        <NodeRow key={n.idx} node={n} byIdx={byIdx} depth={0} defaultOpen hook={hook} interesting={interesting} />
      ))}
    </ul>
  );
}

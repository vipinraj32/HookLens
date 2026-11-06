"use client";

import { ArrowRight, FileSearch, FlaskConical, HelpCircle } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { Badge, Card, CardBody, CardHeader, CopyButton, EmptyState, KV, Mono, Notice, SeverityBadge, StatusBadge } from "@/components/ui";
import type { Finding, PermissionFlag, Scan } from "@/lib/api/models";
import { cn, humanize } from "@/lib/format";

/** Pool operation each v4 callback runs in (v4-core Hooks.sol). */
const OPERATIONS: { id: string; label: string; callbacks: string[] }[] = [
  { id: "initialize", label: "Initialize", callbacks: ["beforeInitialize", "afterInitialize"] },
  { id: "add", label: "Add liquidity", callbacks: ["beforeAddLiquidity", "afterAddLiquidity", "afterAddLiquidityReturnDelta"] },
  { id: "remove", label: "Remove liquidity", callbacks: ["beforeRemoveLiquidity", "afterRemoveLiquidity", "afterRemoveLiquidityReturnDelta"] },
  { id: "swap", label: "Swap", callbacks: ["beforeSwap", "afterSwap", "beforeSwapReturnDelta", "afterSwapReturnDelta"] },
  { id: "donate", label: "Donate", callbacks: ["beforeDonate", "afterDonate"] },
];

/**
 * Lab scenarios that exercise a callback. This is a static map of which scenario targets
 * which pool operation; it says nothing about a result until the scenario is actually run.
 */
const SCENARIOS_FOR: Record<string, string[]> = {
  remove: ["withdrawal_failure", "oracle_failure", "accounting_invariants"],
  add: ["accounting_invariants"],
  swap: ["fee_escalation", "accounting_invariants", "transaction_ordering"],
  initialize: [],
  donate: [],
};

const WITHDRAWAL = new Set(["beforeRemoveLiquidity", "afterRemoveLiquidity", "afterRemoveLiquidityReturnDelta"]);

function flagKey(f: PermissionFlag) {
  return (f as { field?: string }).field ?? f.callback ?? f.flag;
}

function opOf(name: string) {
  return OPERATIONS.find((o) => o.callbacks.includes(name));
}

function related(findings: Finding[], f: PermissionFlag) {
  const names = new Set([flagKey(f), f.callback].filter(Boolean) as string[]);
  return findings.filter(
    (x) => x.affected_functions.some((fn) => names.has(fn.split("(")[0])) || [...names].some((n) => x.title.includes(n)),
  );
}

export function PermissionMatrix({ scan, findings }: { scan: Scan; findings: Finding[] | undefined }) {
  const p = scan.permissions;
  const flags = useMemo(() => p?.flags ?? [], [p]);
  const byName = useMemo(() => new Map(flags.map((f) => [flagKey(f), f])), [flags]);
  const firstEnabled = flags.find((f) => f.enabled);
  const [sel, setSel] = useState<string | null>(firstEnabled ? flagKey(firstEnabled) : null);
  const caps = scan.analysis.capabilities as { source_analysis?: boolean; unavailable?: (string | { capability?: string; reason?: string })[] } | null | undefined;
  const sourceKnown = caps?.source_analysis !== false;

  if (!p) return <EmptyState title="Permissions unavailable">The scan did not reach permission decoding.</EmptyState>;

  const current = sel ? byName.get(sel) : undefined;
  const rel = current && findings ? related(findings, current) : [];
  const op = current ? opOf(flagKey(current)) : undefined;
  const scenarioIds = [...new Set([...rel.flatMap((f) => f.related_scenarios), ...(op ? SCENARIOS_FOR[op.id] : [])])];
  const evidenceIds = [...new Set(rel.flatMap((f) => f.evidence_ids))];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className="text-muted">
          Address bits <span className="font-mono text-fg">{p.bits}</span>
        </span>
        <span className="text-muted">
          {p.enabled_flags?.length ?? flags.filter((f) => f.enabled).length} of {flags.length} callbacks enabled
        </span>
        {p.can_affect_withdrawals ? <Badge className="border-warn/40 text-warn">can affect withdrawals</Badge> : null}
        {p.return_delta_flags?.length ? <Badge className="border-warn/40 text-warn">return-delta enabled</Badge> : null}
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1fr)]">
        <div className="self-start overflow-x-auto rounded-2xl border border-line bg-surface p-3">
          <table className="w-full min-w-[30rem] border-separate border-spacing-1.5 text-sm">
            <caption className="sr-only">Hook permissions by pool operation. Select a callback for details.</caption>
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-faint">
                <th scope="col" className="px-2 font-medium">Operation</th>
                <th scope="col" className="px-2 font-medium">Before</th>
                <th scope="col" className="px-2 font-medium">After</th>
                <th scope="col" className="px-2 font-medium">Return delta</th>
              </tr>
            </thead>
            <tbody>
              {OPERATIONS.map((o) => {
                const before = o.callbacks.find((c) => c.startsWith("before") && !c.endsWith("ReturnDelta"));
                const after = o.callbacks.find((c) => c.startsWith("after") && !c.endsWith("ReturnDelta"));
                const deltas = o.callbacks.filter((c) => c.endsWith("ReturnDelta"));
                const cell = (name: string | undefined) => {
                  const f = name ? byName.get(name) : undefined;
                  if (!name || !f) return <span className="block px-2 py-2 text-xs text-faint">—</span>;
                  const on = f.enabled;
                  const lp = on && (WITHDRAWAL.has(name) || f.is_return_delta);
                  return (
                    <button
                      key={name}
                      type="button"
                      onClick={() => setSel(name)}
                      aria-pressed={sel === name}
                      aria-label={`${name}, ${on ? "enabled" : "disabled"}`}
                      title={f.explanation ?? undefined}
                      className={cn(
                        "flex w-full items-center gap-2 rounded-lg border px-2 py-1.5 text-left font-mono text-[11.5px] transition-colors",
                        on ? (lp ? "border-warn/50 bg-warn/10 text-fg" : "border-line-strong bg-surface-2 text-fg") : "border-line/70 text-faint hover:text-muted",
                        sel === name && "ring-1 ring-fg/40",
                      )}
                    >
                      <span aria-hidden="true" className={cn("size-1.5 shrink-0 rounded-full", on ? (lp ? "bg-warn" : "bg-accent") : "bg-line")} />
                      <span className="truncate">{name.endsWith("ReturnDelta") ? name.replace(/ReturnDelta$/, "Δ") : name.replace(/^(before|after)/, "")}</span>
                    </button>
                  );
                };
                return (
                  <tr key={o.id}>
                    <th scope="row" className="whitespace-nowrap px-2 text-left text-xs font-medium text-muted">
                      {o.label}
                    </th>
                    <td>{cell(before)}</td>
                    <td>{cell(after)}</td>
                    <td>
                      <div className="flex flex-col gap-1">{deltas.length ? deltas.map((d) => cell(d)) : cell(undefined)}</div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="mt-2 px-2 text-[11px] text-faint">
            <span className="mr-3">
              <span aria-hidden="true" className="mr-1 inline-block size-1.5 rounded-full bg-accent" />
              enabled
            </span>
            <span className="mr-3">
              <span aria-hidden="true" className="mr-1 inline-block size-1.5 rounded-full bg-warn" />
              enabled, affects withdrawals or settled amounts
            </span>
            <span>
              <span aria-hidden="true" className="mr-1 inline-block size-1.5 rounded-full bg-line" />
              off
            </span>
          </p>
        </div>

        <Card>
          {current ? (
            <>
              <CardHeader
                title={<span className="font-mono">{flagKey(current)}</span>}
                description={`${op?.label ?? "Pool operation"} · bit ${current.bit}`}
                actions={current.enabled ? <Badge className="border-accent/50 text-accent">enabled</Badge> : <Badge>off</Badge>}
              />
              <CardBody className="flex flex-col gap-4">
                <p className="text-sm text-muted">{current.explanation ?? "No explanation recorded for this flag."}</p>
                <KV
                  items={[
                    ["Signature", current.signature ? <span key="s" className="break-all font-mono text-xs">{current.signature}</span> : "—"],
                    ["Selector", current.selector ? <Mono key="sel" value={current.selector} /> : "—"],
                    ["Evidence basis", "hook address bits (v4 Hooks.sol)"],
                  ]}
                />
                {!current.enabled ? (
                  <p className="text-xs text-faint">
                    The address bit is off, so the PoolManager never calls this callback for pools using this hook.
                  </p>
                ) : !sourceKnown ? (
                  <Notice tone="warn">
                    <HelpCircle aria-hidden="true" className="mr-1 inline size-4" />
                    Unknown: no verified source. The bit only shows that it runs.
                  </Notice>
                ) : null}

                <div>
                  <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-faint">Related findings ({rel.length})</p>
                  {findings === undefined ? (
                    <p className="text-xs text-faint">Findings are not loaded yet.</p>
                  ) : rel.length === 0 ? (
                    <p className="text-xs text-faint">No finding names this callback.</p>
                  ) : (
                    <ul className="flex flex-col gap-1.5">
                      {rel.map((f) => (
                        <li key={f.finding_id}>
                          <Link
                            href={`/app/scans/${scan.id}?finding=${f.finding_id}`}
                            className="flex items-center gap-2 rounded-md border border-line px-2.5 py-1.5 text-sm transition-colors hover:border-line-strong hover:bg-surface-2"
                          >
                            <SeverityBadge severity={f.severity} />
                            <span className="min-w-0 flex-1 truncate">{f.title}</span>
                            <ArrowRight aria-hidden="true" className="size-3.5 shrink-0 text-faint" />
                          </Link>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>

                {evidenceIds.length ? (
                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="text-faint">{evidenceIds.length} evidence item{evidenceIds.length === 1 ? "" : "s"}</span>
                    <Link
                      href={`/app/evidence?scan=${scan.id}&q=${encodeURIComponent(flagKey(current))}`}
                      className="inline-flex items-center gap-1 text-accent hover:underline"
                    >
                      <FileSearch aria-hidden="true" className="size-3.5" /> Open in evidence explorer
                    </Link>
                    <CopyButton value={evidenceIds.join(", ")} label="Copy IDs" />
                  </div>
                ) : null}

                {current.enabled && scenarioIds.length ? (
                  <div>
                    <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-faint">Test it in the lab</p>
                    <div className="flex flex-wrap gap-2">
                      {scenarioIds.map((sid) => (
                        <Link
                          key={sid}
                          href={`/app/scans/${scan.id}/lab?scenario=${sid}`}
                          className="inline-flex items-center gap-1.5 rounded-full border border-line px-3 py-1 text-xs text-muted hover:border-line-strong hover:text-fg"
                        >
                          <FlaskConical aria-hidden="true" className="size-3.5" /> {humanize(sid)}
                        </Link>
                      ))}
                    </div>
                  </div>
                ) : null}
              </CardBody>
            </>
          ) : (
            <EmptyState title="Select a callback">See what it allows, its selector, related findings and lab tests.</EmptyState>
          )}
        </Card>
      </div>

      <RiskProfile scan={scan} findings={findings} />

      {p.note ? <p className="text-xs text-faint">{p.note}</p> : null}
      {p.v4_core_commit ? (
        <p className="text-xs text-faint">
          Decoded with v4-core <span className="font-mono">{p.v4_core_commit.slice(0, 12)}</span> · Hooks.sol sha256{" "}
          <span className="font-mono">{p.hooks_sol_sha256?.slice(0, 16)}…</span>
        </p>
      ) : null}
    </div>
  );
}

const UNKNOWN = <span className="text-faint">unknown</span>;

/** Proxy, admin, dependency, fee and accounting facts. Anything not analyzed says "unknown". */
function RiskProfile({ scan, findings }: { scan: Scan; findings: Finding[] | undefined }) {
  const caps = scan.analysis.capabilities as { source_analysis?: boolean } | null | undefined;
  const source = caps?.source_analysis !== false;
  const facts = (scan.analysis.facts ?? {}) as { bytecode_external_targets?: string[] };
  const byCat = (cats: string[]) => (findings ?? []).filter((f) => cats.includes(f.category));
  const count = (cats: string[]) => {
    if (findings === undefined) return <span className="text-faint">loading…</span>;
    if (!source) return UNKNOWN;
    const n = byCat(cats).length;
    return n === 0 ? <span className="text-muted">no finding</span> : `${n} finding${n === 1 ? "" : "s"}`;
  };
  const c = scan.contract;
  const dynamic = scan.pools.filter((p) => p.dynamic_fee).length;
  const targets = facts.bytecode_external_targets ?? [];
  const deltas = scan.permissions?.return_delta_flags ?? [];

  return (
    <Card>
      <CardHeader title="Control & dependency profile" description="Not analyzed means unknown, never safe." />
      <CardBody>
        <KV
          items={[
            [
              "Proxy",
              c ? (
                c.is_proxy ? (
                  <span key="p" className="flex flex-wrap items-center gap-2">
                    <StatusBadge status={c.proxy_kind ?? "proxy"} /> implementation <Mono value={c.implementation_address} short />
                  </span>
                ) : (
                  "not a recognised proxy pattern"
                )
              ) : (
                UNKNOWN
              ),
            ],
            ["Admin & access control", count(["access-control", "upgradeability"])],
            [
              "External dependencies",
              <span key="d" className="flex flex-col gap-1">
                <span>{count(["oracle", "external-calls"])}</span>
                {targets.length ? (
                  <span className="flex flex-wrap gap-1 text-xs text-muted">
                    hard-coded call targets in bytecode:
                    {targets.map((t) => (
                      <Mono key={t} value={t} short />
                    ))}
                  </span>
                ) : null}
              </span>,
            ],
            [
              "Fees",
              <span key="f">
                {scan.pools.length ? `${dynamic} of ${scan.pools.length} pool${scan.pools.length === 1 ? "" : "s"} use a dynamic fee · ` : "no pools discovered · "}
                {count(["fees"])}
              </span>,
            ],
            [
              "Custom accounting",
              <span key="a">
                {deltas.length ? `return-delta flags: ${deltas.join(", ")} · ` : "no return-delta flags · "}
                {count(["accounting"])}
              </span>,
            ],
          ]}
        />
      </CardBody>
    </Card>
  );
}

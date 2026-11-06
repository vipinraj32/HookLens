"use client";

import { ArrowDownLeft, ArrowUpRight, CheckCircle2, CircleSlash, XCircle } from "lucide-react";
import type { ReactNode } from "react";

import { HOOK_CALLBACKS, RevertMessage, TraceTree } from "@/components/trace";
import { Badge, Card, CardBody, CardHeader, CodeBlock, KV, Mono, StatusBadge } from "@/components/ui";
import type { Chain, Pool, ScenarioRun, Simulation, Step, Trace, TraceNode } from "@/lib/api/models";
import { cn, formatUnits, groupDecimal, humanize } from "@/lib/format";

const GOOD = new Set(["passed", "expected_revert"]);
const BAD = new Set(["failed", "unexpected_revert"]);

function tone(status: string) {
  return GOOD.has(status) ? "ok" : BAD.has(status) ? "bad" : "neutral";
}

/* ------------------------------------------------------------------ timeline */

export function StepTimeline({ steps, selected, onSelect }: { steps: Step[]; selected: string | null; onSelect: (s: Step) => void }) {
  // Consecutive steps of the same phase form one group.
  const groups: { phase: string; steps: Step[] }[] = [];
  for (const s of steps) {
    const last = groups.at(-1);
    if (last && last.phase === s.phase) last.steps.push(s);
    else groups.push({ phase: s.phase, steps: [s] });
  }
  return (
    <ol aria-label="Scenario steps" className="flex flex-col gap-3">
      {groups.map((g, gi) => (
        <li key={`${g.phase}-${gi}`} className="relative pl-5">
          <span aria-hidden="true" className="absolute bottom-0 left-[5px] top-6 w-px bg-line" />
          <p className="mb-1.5 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-faint">
            <span aria-hidden="true" className="absolute left-0 top-1 size-[11px] rounded-full border-2 border-violet bg-bg" />
            {humanize(g.phase)}
          </p>
          <ul className="flex flex-wrap gap-1.5">
            {g.steps.map((s) => {
              const t = tone(s.step_status);
              const Icon = t === "ok" ? CheckCircle2 : t === "bad" ? XCircle : CircleSlash;
              return (
                <li key={s.name}>
                  <button
                    type="button"
                    onClick={() => onSelect(s)}
                    aria-pressed={selected === s.name}
                    title={`${s.name}: expected ${s.lp_expectation}, observed ${s.observed} (${s.step_status})`}
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 font-mono text-xs transition-colors",
                      t === "ok" && "border-ok/30 hover:border-ok/60",
                      t === "bad" && "border-bad/40 bg-bad/5 hover:border-bad/70",
                      t === "neutral" && "border-line hover:border-muted",
                      selected === s.name && "bg-surface-2 ring-2 ring-accent",
                    )}
                  >
                    <Icon aria-hidden="true" className={cn("size-3.5", t === "ok" ? "text-ok" : t === "bad" ? "text-bad" : "text-faint")} />
                    {s.name}
                    {s.privileged ? <span className="rounded bg-warn/15 px-1 text-[10px] text-warn">priv</span> : null}
                    <span className="sr-only">, {s.step_status}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </li>
      ))}
    </ol>
  );
}

/* ------------------------------------------------------------------ token deltas */

function DeltaRow({ symbol, raw, decimals, source }: { symbol: string; raw: string | undefined; decimals: number | null | undefined; source?: string | null }) {
  if (raw === undefined) return null;
  const human = formatUnits(raw, decimals);
  const neg = raw.startsWith("-");
  const zero = /^-?0+$/.test(raw);
  return (
    <div className="grid grid-cols-[6rem_minmax(0,1fr)] items-center gap-3 rounded-lg border border-line bg-bg px-3 py-2 sm:grid-cols-[7rem_8rem_minmax(0,1fr)]">
      <span className="text-sm font-medium">{symbol}</span>
      <span
        className={cn(
          "inline-flex w-fit items-center gap-1 rounded-full px-2 py-0.5 text-xs",
          zero ? "text-faint" : neg ? "bg-violet/10 text-violet" : "bg-accent/10 text-accent",
        )}
      >
        {zero ? null : neg ? <ArrowUpRight aria-hidden="true" className="size-3.5" /> : <ArrowDownLeft aria-hidden="true" className="size-3.5" />}
        {zero ? "no change" : neg ? "paid to pool" : "received"}
      </span>
      <span className="col-span-2 flex min-w-0 flex-col sm:col-span-1">
        <span className="font-mono text-sm tabular-nums">
          {human ?? "decimals unknown"} {human ? symbol : ""}
        </span>
        <span className="break-all font-mono text-[11px] text-faint">
          raw {raw}
          {decimals !== null && decimals !== undefined ? ` · ${decimals} decimals${source ? ` (${source})` : ""}` : ""}
        </span>
      </span>
    </div>
  );
}

export function TokenDeltas({ step, pool }: { step: Step; pool: Pool | undefined }) {
  if (step.amount0 === undefined && step.amount1 === undefined) return null;
  return (
    <div>
      <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-faint">Token deltas</p>
      <div className="flex flex-col gap-1.5">
        <DeltaRow symbol={pool?.token0?.symbol ?? "token0"} raw={step.amount0} decimals={pool?.token0?.decimals} source={pool?.token0?.decimals_source} />
        <DeltaRow symbol={pool?.token1?.symbol ?? "token1"} raw={step.amount1} decimals={pool?.token1?.decimals} source={pool?.token1?.decimals_source} />
      </div>
      <p className="mt-1.5 text-[11px] text-faint">
        Sign convention: v4 BalanceDelta from the acting account&apos;s side. Negative means the account paid tokens
        into the pool; positive means it received tokens. Amounts are exact integers scaled by the token&apos;s decimals.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ step detail */

function collect(trace: Trace, roots: number[]): TraceNode[] {
  const by = new Map((trace.nodes ?? []).map((n) => [n.idx, n]));
  const out: TraceNode[] = [];
  const stack = [...roots];
  while (stack.length) {
    const n = by.get(stack.pop()!);
    if (!n) continue;
    out.push(n);
    stack.push(...(n.children ?? []));
  }
  return out;
}

export function StepDetail({ run, step, pool, hook }: { run: ScenarioRun; step: Step; pool: Pool | undefined; hook: string }) {
  const roots = step.trace_nodes ?? run.trace.steps?.[step.name] ?? [];
  const frames = collect(run.trace, roots);
  const hookLc = hook.toLowerCase();
  const hookCalls = frames.filter((n) => n.address.toLowerCase() === hookLc && HOOK_CALLBACKS.has((n.function ?? "").split("(")[0]));
  const logs = frames.reduce((a, n) => a + (n.log_count ?? 0), 0);
  const hasLogInfo = frames.some((n) => n.log_count !== undefined);
  const met = step.expectation_met;

  return (
    <Card>
      <CardHeader
        title={<span className="font-mono">{step.name}</span>}
        description={step.note}
        actions={
          <>
            {step.privileged ? <Badge className="border-warn/40 text-warn">privileged (impersonated on fork)</Badge> : null}
            <StatusBadge status={step.step_status} />
          </>
        }
      />
      <CardBody className="flex flex-col gap-5">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          <div className="rounded-lg border border-line bg-bg p-3">
            <p className="text-[11px] uppercase tracking-wide text-faint">LP expects</p>
            <p className="mt-1 font-mono text-sm">{step.lp_expectation}</p>
            <p className="mt-1 text-xs text-faint">condition: {step.condition}</p>
          </div>
          <div className={cn("rounded-lg border p-3", met ? "border-ok/30 bg-ok/5" : "border-bad/30 bg-bad/5")}>
            <p className="text-[11px] uppercase tracking-wide text-faint">Observed on fork</p>
            <p className={cn("mt-1 font-mono text-sm", met ? "text-ok" : "text-bad")}>{step.observed}</p>
            <p className="mt-1 text-xs text-faint">{met ? "matches the expectation" : "does not match the expectation"}</p>
          </div>
        </div>

        {step.revert ? (
          <div className="rounded-lg border border-bad/30 bg-bad/5 p-3">
            <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-faint">Decoded revert</p>
            <RevertMessage revert={step.revert} />
          </div>
        ) : null}
        {step.revert_chain?.length ? (
          <div>
            <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-faint">Failing call path</p>
            <ol className="flex flex-col gap-1 border-l border-bad/40 pl-3 font-mono text-xs">
              {step.revert_chain.map((f, i, all) => (
                <li key={f.idx} className="flex flex-wrap gap-2">
                  <span className="text-faint">{i + 1}.</span>
                  <span className={f.address.toLowerCase() === hookLc ? "text-accent" : "text-violet"}>{f.label ?? f.address}</span>
                  <span>{f.function?.split("(")[0] ?? f.selector}</span>
                  {i === all.length - 1 && f.revert?.message ? <span className="text-bad">→ {f.revert.message}</span> : null}
                </li>
              ))}
            </ol>
          </div>
        ) : null}

        <TokenDeltas step={step} pool={pool} />

        <KV
          items={[
            ["Gas used", step.gas_used !== undefined ? step.gas_used.toLocaleString() : "not recorded"],
            ["Block timestamp", step.block_timestamp ?? "not recorded"],
            ["Hook callbacks in this step", hookCalls.length ? hookCalls.map((n) => (n.function ?? "").split("(")[0]).join(", ") : "none in the trace"],
            ["Events emitted", hasLogInfo ? `${logs} log${logs === 1 ? "" : "s"} across ${frames.length} frames` : "not recorded"],
            ["Raw revert data", step.revert_data && step.revert_data !== "0x" ? <Mono key="rd" value={step.revert_data} short /> : "none"],
          ]}
        />

        <div>
          <p className="mb-1.5 flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-wide text-faint">
            Trace explorer
            <span className="font-normal normal-case text-faint">
              <span aria-hidden="true" className="mr-1 inline-block size-2 rounded-sm bg-accent/40" />
              hook callback frames
            </span>
          </p>
          <TraceTree trace={run.trace} roots={roots} hook={hook} />
        </div>
      </CardBody>
    </Card>
  );
}

/* ------------------------------------------------------------------ invariants */

type Metrics = Record<string, string | boolean | number>;

export function InvariantPanel({ run }: { run: ScenarioRun }) {
  const inv = run.steps.filter((s) => s.phase === "invariant");
  const withMetrics = run.steps.filter((s) => (s as { metrics?: Metrics }).metrics);
  if (!inv.length && !withMetrics.length) return null;
  const checks: { label: string; key: keyof Metrics }[] = [
    { label: "Actor delta matches", key: "actor_delta_matches" },
    { label: "Value conserved", key: "value_conserved" },
  ];
  return (
    <Card>
      <CardHeader
        title="Invariants evaluated"
        description="Only checks the harness actually evaluated in this run are listed."
      />
      <CardBody className="flex flex-col gap-4">
        {inv.length ? (
          <ul className="flex flex-col gap-1.5">
            {inv.map((s) => (
              <li key={s.name} className="flex flex-wrap items-center gap-2 rounded-lg border border-line px-3 py-2 text-sm">
                <StatusBadge status={s.step_status} />
                <span className="font-mono text-xs">{s.name}</span>
                <span className="text-xs text-muted">
                  expects {s.lp_expectation}, observed {s.observed}
                  {s.condition && s.condition !== "baseline" ? ` · ${humanize(s.condition)}` : ""}
                </span>
              </li>
            ))}
          </ul>
        ) : null}
        {withMetrics.length ? (
          <div className="overflow-x-auto rounded-lg border border-line">
            <table className="w-full min-w-[40rem] text-xs">
              <thead className="bg-surface text-left uppercase tracking-wide text-faint">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">Step</th>
                  {checks.map((c) => (
                    <th key={c.key} scope="col" className="px-3 py-2 font-medium">{c.label}</th>
                  ))}
                  <th scope="col" className="px-3 py-2 text-right font-medium">Hook claims Δ0 / Δ1 (raw)</th>
                </tr>
              </thead>
              <tbody>
                {withMetrics.map((s) => {
                  const m = (s as { metrics?: Metrics }).metrics!;
                  return (
                    <tr key={s.name} className="border-t border-line/60">
                      <td className="px-3 py-2 font-mono">{s.name}</td>
                      {checks.map((c) => (
                        <td key={c.key} className="px-3 py-2">
                          {m[c.key] === undefined ? (
                            <span className="text-faint">not evaluated</span>
                          ) : m[c.key] ? (
                            <span className="text-ok">yes</span>
                          ) : (
                            <span className="font-medium text-bad">no</span>
                          )}
                        </td>
                      ))}
                      <td className="px-3 py-2 text-right font-mono text-muted">
                        {m.hook_claims_change0 !== undefined ? `${groupDecimal(String(m.hook_claims_change0))} / ${groupDecimal(String(m.hook_claims_change1))}` : "—"}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

/* ------------------------------------------------------------------ fork context */

export function ForkContext({ sim, chain, run }: { sim: Simulation; chain: Chain | undefined; run?: ScenarioRun }) {
  const harness = sim.spec.harness as { version?: string; digest?: string } | undefined;
  const meta = (run?.result_meta ?? {}) as { pool_manager?: string; hook?: string; tick_lower?: number; tick_upper?: number; liquidity?: string; initial_tick?: number };
  const rows: [ReactNode, ReactNode][] = [
    ["Chain", chain ? `${chain.name} (${chain.chain_id})` : sim.chain_id],
    ["Fork block", sim.fork_block ?? "not recorded"],
    ["Block hash", sim.fork_block_hash ? <Mono key="bh" value={sim.fork_block_hash} short /> : "not recorded"],
    ["Pool", sim.pool_id ? <Mono key="p" value={sim.pool_id} short /> : "—"],
    ["Harness", `${harness?.version ?? sim.harness_version ?? "—"}${sim.harness_commit ? ` · commit ${sim.harness_commit.slice(0, 10)}` : ""}`],
  ];
  if (harness?.digest) rows.push(["Harness digest", <Mono key="d" value={harness.digest} short />]);
  if (meta.pool_manager) rows.push(["PoolManager", <Mono key="pm" value={meta.pool_manager} short />]);
  if (meta.tick_lower !== undefined) rows.push(["Test position", `[${meta.tick_lower}, ${meta.tick_upper}) · start tick ${meta.initial_tick ?? "?"}`]);
  return (
    <Card>
      <CardHeader title="Fork context" description="Everything this result depends on. RPC endpoints are server-side and never shown." />
      <CardBody className="flex flex-col gap-4">
        <KV items={rows} />
        {run ? (
          <div>
            <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-faint">Reproduce {humanize(run.scenario_id)}</p>
            <CodeBlock code={run.repro_command} />
            <p className="mt-1.5 text-[11px] text-faint">Replace the RPC placeholder with your own archive endpoint or a local Anvil URL.</p>
          </div>
        ) : null}
      </CardBody>
    </Card>
  );
}

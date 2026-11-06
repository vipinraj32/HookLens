"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FlaskConical, Gauge, Info, Play, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useId, useMemo, useState, type FormEvent } from "react";

import { JobProgress } from "@/components/job-progress";
import { ForkContext, InvariantPanel, StepDetail, StepTimeline } from "@/components/lab";
import { Elapsed, OutcomeBadge, OutcomeLegend, ScenarioCard, ScenarioIcon } from "@/components/scenarios";
import {
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorState,
  Field,
  KV,
  Mono,
  Notice,
  Skeleton,
  Spinner,
  StatusBadge,
  inputClass,
} from "@/components/ui";
import {
  isTerminal,
  keys,
  useChains,
  useCreateSimulation,
  useScan,
  useScenarioRun,
  useScenarios,
  useSimulation,
  useSimulations,
  useWorkerHealth,
  type SimulationCreateBody,
} from "@/lib/api/hooks";
import { useJobStream } from "@/lib/api/jobs";
import type { Chain, Pool, Scan, ScenarioRunSummary, Simulation } from "@/lib/api/models";
import { cn, formatDate, formatDuration, humanize } from "@/lib/format";
import { OUTCOME, OUTCOMES, outcomeOf, type OutcomeClass } from "@/lib/outcomes";

const STATUS_RANK: Record<string, number> = {
  unexpected_revert: 0,
  failed: 0,
  infra_error: 1,
  timed_out: 1,
  partial: 2,
  inconclusive: 2,
  passed: 3,
  expected_revert: 3,
  cancelled: 4,
  skipped: 6,
  unsupported: 7,
};

type ScenarioId = NonNullable<SimulationCreateBody["scenarios"]>[number];

const WHOLE = /^\d{1,60}$/;

function poolLabel(p: Pool | undefined) {
  if (!p) return "—";
  return `${p.token0?.symbol ?? "?"} / ${p.token1?.symbol ?? "?"}`;
}

// ---------------------------------------------------------------- console header

function LabConsole({ scan, chain, poolId }: { scan: Scan; chain: Chain | undefined; poolId: string | undefined }) {
  const health = useWorkerHealth();
  const pool = scan.pools.find((p) => p.pool_id === poolId) ?? scan.pools[0];
  const forge = health.data?.forge.available;
  return (
    <section
      aria-label="Lab target"
      className="lab-console mb-6 overflow-hidden rounded-2xl border border-line bg-surface"
    >
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-line px-5 py-4">
        <div className="min-w-0">
          <p className="flex items-center gap-2 font-mono text-[11px] uppercase tracking-widest text-faint">
            <FlaskConical aria-hidden="true" className="size-3.5" /> Adversarial Lab
          </p>
          <h1 className="mt-1 truncate text-2xl font-semibold tracking-tight">{scan.contract?.contract_name ?? "Hook"}</h1>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button asChild>
            <Link href={`/app/scans/${scan.id}`}>
              <ArrowLeft aria-hidden="true" className="size-4" /> Hook Intelligence
            </Link>
          </Button>
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-px bg-line text-sm sm:grid-cols-3 xl:grid-cols-5">
        {[
          ["Hook", <Mono key="h" value={scan.hook_address} short />],
          ["Pool", pool ? <span key="p" className="font-medium">{poolLabel(pool)}</span> : <span key="p" className="text-faint">none discovered</span>],
          ["Chain", chain ? `${chain.name} · ${chain.chain_id}` : String(scan.chain_id)],
          ["Pinned block", scan.block_number ? <span key="b" className="font-mono tabular-nums">{scan.block_number}</span> : "latest at run time"],
          [
            "Foundry",
            health.isPending ? (
              <Skeleton key="f" className="h-4 w-20" />
            ) : forge === undefined ? (
              <span key="f" className="text-faint">unknown</span>
            ) : (
              <span key="f" className={cn("inline-flex items-center gap-1.5", forge ? "text-ok" : "text-bad")}>
                <span aria-hidden="true" className={cn("size-1.5 rounded-full", forge ? "bg-ok" : "bg-bad")} />
                {forge ? "available" : "unavailable"}
              </span>
            ),
          ],
        ].map(([k, v]) => (
          <div key={String(k)} className="min-w-0 bg-surface px-5 py-3 last:col-span-2 xl:last:col-span-1">
            <dt className="text-[11px] uppercase tracking-wide text-faint">{k}</dt>
            <dd className="mt-1 truncate">{v}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

// ---------------------------------------------------------------- run form

function RunForm({
  scan,
  poolId,
  setPoolId,
  lastByScenario,
  onStarted,
}: {
  scan: Scan;
  poolId: string;
  setPoolId: (id: string) => void;
  lastByScenario: Map<string, string>;
  onStarted: (sim: Simulation) => void;
}) {
  const id = useId();
  const params = useSearchParams();
  const scenarios = useScenarios();
  const health = useWorkerHealth();
  const create = useCreateSimulation(scan.id);
  const preset = params.get("scenario");
  const [selected, setSelected] = useState<Set<string> | null>(preset ? new Set([preset]) : null);
  const [adv, setAdv] = useState({ tick_lower: "", tick_upper: "", liquidity: "", amount0: "", amount1: "", swap_amount0: "", swap_amount1: "" });
  const [error, setError] = useState<string | null>(null);
  const all = scenarios.data?.map((s) => s.scenario_id) ?? [];
  const chosen = selected ?? new Set(all);
  const pool = scan.pools.find((p) => p.pool_id === poolId);
  const forgeMissing = health.data ? !health.data.forge.available : false;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const v = Object.fromEntries(Object.entries(adv).map(([k, x]) => [k, x.trim()])) as typeof adv;
    if ((v.tick_lower === "") !== (v.tick_upper === "")) return setError("Provide both ticks or neither.");
    if (v.tick_lower && (!/^-?\d+$/.test(v.tick_lower) || !/^-?\d+$/.test(v.tick_upper))) return setError("Ticks must be integers.");
    if (v.tick_lower && Number(v.tick_lower) >= Number(v.tick_upper)) return setError("tick_lower must be below tick_upper.");
    if (v.tick_lower && pool && (Number(v.tick_lower) % pool.tick_spacing !== 0 || Number(v.tick_upper) % pool.tick_spacing !== 0)) {
      return setError(`Ticks must be multiples of the pool's tick spacing (${pool.tick_spacing}).`);
    }
    if (v.liquidity && !/^\d{1,39}$/.test(v.liquidity)) return setError("Liquidity must be a whole number (uint128).");
    for (const k of ["amount0", "amount1", "swap_amount0", "swap_amount1"] as const) {
      if (v[k] && !WHOLE.test(v[k])) return setError(`${humanize(k)} must be a whole number of raw token units.`);
    }
    if (chosen.size === 0) return setError("Select at least one scenario.");
    create.mutate(
      {
        pool_id: poolId || null,
        scenarios: [...chosen] as ScenarioId[],
        tick_lower: v.tick_lower ? Number(v.tick_lower) : null,
        tick_upper: v.tick_upper ? Number(v.tick_upper) : null,
        liquidity: v.liquidity || null,
        amount0: v.amount0 || null,
        amount1: v.amount1 || null,
        swap_amount0: v.swap_amount0 || null,
        swap_amount1: v.swap_amount1 || null,
      },
      { onSuccess: onStarted },
    );
  };

  if (scan.pools.length === 0) {
    return (
      <EmptyState title="No pool to simulate">
        No initialized pool found. Re-scan with a pool ID.
      </EmptyState>
    );
  }

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-5">
      {scan.pools.length > 1 ? (
        <Field id={`${id}-pool`} label="Pool">
          <select id={`${id}-pool`} value={poolId} onChange={(e) => setPoolId(e.target.value)} className={`${inputClass} font-mono`}>
            {scan.pools.map((p) => (
              <option key={p.pool_id} value={p.pool_id}>
                {poolLabel(p)} · {p.pool_id.slice(0, 18)}…
              </option>
            ))}
          </select>
        </Field>
      ) : null}

      <fieldset>
        <legend className="mb-3 flex w-full flex-wrap items-center justify-between gap-2 text-sm font-medium">
          <span>
            Scenarios <span className="font-normal text-faint">· {chosen.size} of {all.length || "…"} selected</span>
          </span>
          {scenarios.data ? (
            <span className="flex gap-1 text-xs font-normal">
              <button type="button" className="rounded-md px-2 py-1 text-fg hover:bg-surface-2" onClick={() => setSelected(new Set(all))}>
                Select all
              </button>
              <button type="button" className="rounded-md px-2 py-1 text-muted hover:bg-surface-2" onClick={() => setSelected(new Set())}>
                Clear
              </button>
            </span>
          ) : null}
        </legend>
        {scenarios.isPending ? (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-24" />
            ))}
          </div>
        ) : null}
        {scenarios.isError ? <ErrorState error={scenarios.error} onRetry={() => scenarios.refetch()} /> : null}
        <div role="group" aria-label="Scenarios" className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {scenarios.data?.map((s) => (
            <ScenarioCard
              key={s.scenario_id}
              scenario={s}
              selected={chosen.has(s.scenario_id)}
              lastStatus={lastByScenario.get(s.scenario_id)}
              onToggle={(on) => {
                const next = new Set(chosen);
                if (on) next.add(s.scenario_id);
                else next.delete(s.scenario_id);
                setSelected(next);
              }}
            />
          ))}
        </div>
      </fieldset>

      <details className="group rounded-xl border border-line bg-bg/40 p-3 open:bg-bg/60">
        <summary className="cursor-pointer text-sm text-muted hover:text-fg">Advanced parameters</summary>
        <p className="mt-2 text-xs text-faint">Blank = defaults (±100 tick spacings, 10 tokens per side). Raw integer units.</p>
        <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {(["tick_lower", "tick_upper", "liquidity", "amount0", "amount1", "swap_amount0", "swap_amount1"] as const).map((k) => (
            <Field key={k} id={`${id}-${k}`} label={humanize(k)}>
              <input
                id={`${id}-${k}`}
                className={`${inputClass} font-mono`}
                inputMode="numeric"
                value={adv[k]}
                onChange={(e) => setAdv({ ...adv, [k]: e.target.value })}
                placeholder="auto"
              />
            </Field>
          ))}
        </div>
      </details>

      {error ? (
        <p role="alert" className="text-sm text-bad">
          {error}
        </p>
      ) : null}
      {create.isError ? <ErrorState error={create.error} title="Simulation was not started" /> : null}
      {forgeMissing ? (
        <Notice tone="warn">Foundry is unavailable on this server.</Notice>
      ) : null}
      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-surface-2/60 p-3">
        <Button type="submit" variant="primary" loading={create.isPending} disabled={chosen.size === 0}>
          <Play aria-hidden="true" className="size-4" /> Run {chosen.size} scenario{chosen.size === 1 ? "" : "s"} on fork
        </Button>
        <p className="text-xs text-faint">
          {poolLabel(pool)} · {scan.block_number ? `block ${scan.block_number}` : "latest block"} · no keys used
        </p>
      </div>
    </form>
  );
}

// ---------------------------------------------------------------- results

const INFRA = new Set(["infra_error", "timed_out", "cancelled"]);

function RunDetail({
  sim,
  summary,
  pool,
  chain,
  hook,
}: {
  sim: Simulation;
  summary: ScenarioRunSummary;
  pool: Pool | undefined;
  chain: Chain | undefined;
  hook: string;
}) {
  const run = useScenarioRun(sim.id, summary.id);
  const [stepName, setStepName] = useState<string | null>(null);
  const step =
    run.data?.steps.find((s) => s.name === stepName) ??
    run.data?.steps.find((s) => s.step_status === "unexpected_revert" || s.step_status === "failed") ??
    run.data?.steps[0] ??
    null;

  if (summary.status === "unsupported" || summary.status === "skipped") {
    return (
      <Notice>
        <span className="font-medium">{humanize(summary.scenario_id)} was not run.</span> {summary.status_reason} Says nothing
        about the hook.
      </Notice>
    );
  }
  if (run.isPending) return <Spinner label="Loading run, steps and trace…" />;
  if (run.isError) return <ErrorState error={run.error} onRetry={() => run.refetch()} />;
  const r = run.data;
  const meta = r.result_meta as { actors?: Record<string, string>; violations?: number };
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-2">
        <OutcomeBadge status={r.status} />
        <span className="text-sm text-muted">{r.status_reason}</span>
        <span className="ml-auto text-xs text-faint">
          forge {r.forge_status ?? "—"} · {formatDuration(r.duration_ms)}
          {meta.violations !== undefined ? ` · ${meta.violations} violation${meta.violations === 1 ? "" : "s"} recorded` : ""}
        </span>
      </div>
      {INFRA.has(r.status) ? (
        <Notice tone="warn">
          Infrastructure outcome ({humanize(r.status)}). Says nothing about the hook.
        </Notice>
      ) : null}
      {r.error ? <ErrorState title="Run error" error={new Error(String((r.error as { message?: string }).message ?? JSON.stringify(r.error)))} /> : null}

      {r.steps.length ? (
        <Card>
          <CardHeader title="Step timeline" description={`${r.steps.length} steps`} />
          <CardBody>
            <StepTimeline steps={r.steps} selected={step?.name ?? null} onSelect={(s) => setStepName(s.name)} />
          </CardBody>
        </Card>
      ) : (
        <Notice>No steps recorded.</Notice>
      )}

      {step ? <StepDetail run={r} step={step} pool={pool} hook={hook} /> : null}

      <InvariantPanel run={r} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ForkContext sim={sim} chain={chain} run={r} />
        <Card>
          <CardHeader title="Actors" description="Roles impersonated in the fork. No keys." />
          <CardBody>
            {meta.actors && Object.keys(meta.actors).length ? (
              <KV items={Object.entries(meta.actors).map(([k, v]) => [k, <Mono key={k} value={v} />])} />
            ) : (
              <p className="text-sm text-faint">No actors recorded.</p>
            )}
          </CardBody>
        </Card>
      </div>
    </div>
  );
}

function OutcomeSummary({ runs }: { runs: ScenarioRunSummary[] }) {
  const counts = new Map<OutcomeClass, number>();
  for (const r of runs) counts.set(outcomeOf(r.status), (counts.get(outcomeOf(r.status)) ?? 0) + 1);
  const present = OUTCOMES.filter((o) => counts.get(o.id));
  if (!present.length) return null;
  return (
    <div>
      <div aria-hidden="true" className="flex h-1.5 overflow-hidden rounded-full bg-line">
        {present.map((o) => (
          <span key={o.id} className={cn("h-full", o.dot)} style={{ flexGrow: counts.get(o.id) }} />
        ))}
      </div>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        {present.map((o) => (
          <li key={o.id} className="flex items-center gap-1.5">
            <span aria-hidden="true" className={cn("size-2 rounded-full", o.dot)} />
            <span className="font-medium text-fg tabular-nums">{counts.get(o.id)}</span> {o.label.toLowerCase()}
          </li>
        ))}
      </ul>
    </div>
  );
}

function SimulationDetail({ simId, scan }: { simId: string; scan: Scan }) {
  const qc = useQueryClient();
  const sim = useSimulation(simId);
  const chains = useChains();
  const [runId, setRunId] = useState<string | null>(null);
  const running = sim.data ? !isTerminal(sim.data.status) : false;
  const stream = useJobStream(running ? sim.data?.job_id : null, () => {
    void qc.invalidateQueries({ queryKey: keys.sim(simId) });
    void qc.invalidateQueries({ queryKey: ["sims"] });
  });
  if (sim.isPending) return <Skeleton className="h-64" />;
  if (sim.isError) return <ErrorState error={sim.error} onRetry={() => sim.refetch()} />;
  const s = sim.data;
  const runs = s.runs ?? [];
  // Default to the most consequential run: failures before passes, unsupported last.
  const rank = (st: string) => STATUS_RANK[st] ?? 5;
  const ordered = [...runs].sort((a, b) => rank(a.status) - rank(b.status));
  const current = runs.find((r) => r.id === runId) ?? ordered[0];
  const pool = scan.pools.find((p) => p.pool_id === s.pool_id);
  const chain = chains.data?.find((c) => c.chain_id === s.chain_id);
  return (
    <div className="flex flex-col gap-5">
      {running && s.job_id ? (
        <Card className="border-line-strong">
          <CardBody>
            <p className="mb-3 text-xs text-muted">
              Elapsed <Elapsed from={s.created_at} running />
            </p>
            <JobProgress jobId={s.job_id} stream={stream} title="Simulation" />
          </CardBody>
        </Card>
      ) : null}
      {s.error ? <ErrorState title={`Simulation ${s.status}`} error={new Error(String((s.error as { message?: string }).message ?? JSON.stringify(s.error)))} /> : null}

      <Card>
        <CardHeader
          title="Scenario results"
          description={
            <span className="flex flex-wrap gap-x-3 gap-y-1">
              <span>{formatDate(s.created_at)}</span>
              <span>
                fork block <span className="font-mono tabular-nums text-fg">{s.fork_block ?? "?"}</span>
              </span>
              {s.harness_version ? <span>harness {s.harness_version}</span> : null}
              <span>
                {running ? "elapsed " : "took "}
                <Elapsed from={s.created_at} to={s.finished_at} running={running} />
              </span>
            </span>
          }
          actions={
            <>
              <StatusBadge status={s.status} />
              {isTerminal(s.status) ? (
                <Button size="sm" variant="primary" asChild>
                  <Link href={`/app/lp?scan=${s.scan_id}&sim=${s.id}${s.pool_id ? `&pool=${s.pool_id}` : ""}`}>
                    <Gauge aria-hidden="true" className="size-3.5" /> Apply to LP position
                  </Link>
                </Button>
              ) : null}
            </>
          }
        />
        <CardBody className="flex flex-col gap-4">
          <OutcomeSummary runs={runs} />
          {runs.length ? (
            <ul aria-label="Scenario runs" className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
              {ordered.map((r) => {
                const o = OUTCOME[outcomeOf(r.status)];
                const on = current?.id === r.id;
                return (
                  <li key={r.id}>
                    <button
                      type="button"
                      onClick={() => setRunId(r.id)}
                      aria-pressed={on}
                      aria-label={`${humanize(r.scenario_id)}: ${o.label}`}
                      className={cn(
                        "flex h-full w-full flex-col gap-2 rounded-xl border p-3 text-left transition-colors",
                        on ? "border-line-strong bg-surface-2" : "border-line hover:border-line-strong hover:bg-surface-2/60",
                      )}
                    >
                      <span className="flex items-center justify-between gap-2">
                        <span className="flex min-w-0 items-center gap-2 text-sm font-medium">
                          <ScenarioIcon id={r.scenario_id} className="size-4 shrink-0 text-muted" />
                          <span className="truncate">{humanize(r.scenario_id)}</span>
                        </span>
                        <span className="shrink-0 text-[11px] tabular-nums text-faint">{formatDuration(r.duration_ms)}</span>
                      </span>
                      <OutcomeBadge status={r.status} className="self-start" />
                      <span className="line-clamp-2 text-xs text-muted">{r.status_reason}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="text-sm text-faint">{running ? "Waiting for results…" : "No runs recorded."}</p>
          )}
          <details className="rounded-xl border border-line bg-bg/40 p-3">
            <summary className="flex cursor-pointer items-center gap-1.5 text-xs text-muted hover:text-fg">
              <Info aria-hidden="true" className="size-3.5" /> Outcome key
            </summary>
            <div className="mt-3">
              <OutcomeLegend />
            </div>
          </details>
        </CardBody>
      </Card>

      {current && current.status !== "queued" && current.status !== "running" ? (
        <section aria-labelledby="evidence-h" id="execution-evidence" className="scroll-mt-20">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <ShieldAlert aria-hidden="true" className="size-4 text-muted" />
            <h2 id="evidence-h" className="text-base font-semibold">
              Execution evidence · {humanize(current.scenario_id)}
            </h2>
          </div>
          <RunDetail key={current.id} sim={s} summary={current} pool={pool} chain={chain} hook={scan.hook_address} />
        </section>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------- page

export function LabView() {
  const { id } = useParams<{ id: string }>();
  const scan = useScan(id);
  const chains = useChains();
  const sims = useSimulations(id, !!scan.data);
  const [simId, setSimId] = useState<string | null>(null);
  const [poolId, setPoolId] = useState<string | null>(null);
  const current = simId ?? sims.data?.[0]?.id ?? null;
  const ordered = useMemo(() => sims.data ?? [], [sims.data]);
  // Latest recorded status per scenario across this scan's simulations (newest first).
  const lastByScenario = useMemo(() => {
    const m = new Map<string, string>();
    for (const sim of ordered) for (const r of sim.runs ?? []) if (!m.has(r.scenario_id)) m.set(r.scenario_id, r.status);
    return m;
  }, [ordered]);

  if (scan.isPending) {
    return (
      <div className="flex flex-col gap-4">
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-72 w-full" />
      </div>
    );
  }
  if (scan.isError) return <ErrorState error={scan.error} onRetry={() => scan.refetch()} />;
  const s = scan.data;
  const ready = isTerminal(s.status) && s.status !== "failed" && s.status !== "cancelled";
  const chain = chains.data?.find((c) => c.chain_id === s.chain_id);
  const pid = poolId ?? s.pools[0]?.pool_id ?? "";

  return (
    <>
      <LabConsole scan={s} chain={chain} poolId={pid} />

      <Card className="mb-6">
        <CardHeader title="Configure a run" />
        <CardBody>
          {ready ? (
            <RunForm scan={s} poolId={pid} setPoolId={setPoolId} lastByScenario={lastByScenario} onStarted={(sim) => setSimId(sim.id)} />
          ) : (
            <Notice>{s.status === "failed" || s.status === "cancelled" ? "Scan did not complete." : "Waiting for the scan to finish…"}</Notice>
          )}
        </CardBody>
      </Card>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[16rem_minmax(0,1fr)]">
        <Card className="self-start">
          <CardHeader title="Run history" />
          {sims.isError ? (
            <CardBody>
              <ErrorState error={sims.error} onRetry={() => sims.refetch()} />
            </CardBody>
          ) : ordered.length === 0 ? (
            <CardBody>
              <p className="text-sm text-muted">{sims.isPending ? "Loading…" : "No simulations yet."}</p>
            </CardBody>
          ) : (
            <ul className="flex flex-col p-2">
              {ordered.map((sim) => (
                <li key={sim.id}>
                  <button
                    type="button"
                    onClick={() => setSimId(sim.id)}
                    aria-current={current === sim.id ? "true" : undefined}
                    className={cn(
                      "flex w-full flex-col gap-1 rounded-lg px-3 py-2 text-left text-sm hover:bg-surface-2",
                      current === sim.id && "bg-surface-2 ring-1 ring-line-strong",
                    )}
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="text-muted">{formatDate(sim.created_at)}</span>
                      <StatusBadge status={sim.status} />
                    </span>
                    <span className="text-[11px] text-faint">
                      {(sim.runs ?? []).length} scenario{(sim.runs ?? []).length === 1 ? "" : "s"} · block {sim.fork_block ?? "?"}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <div className="min-w-0">
          {current ? (
            <SimulationDetail key={current} simId={current} scan={s} />
          ) : (
            <Card>
              <EmptyState title="No simulation yet" icon={<FlaskConical aria-hidden="true" className="size-8" />}>
                Pick scenarios above and run them.
              </EmptyState>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}

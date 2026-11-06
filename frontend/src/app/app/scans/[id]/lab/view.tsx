"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FlaskConical, Gauge, Play } from "lucide-react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useId, useMemo, useState, type FormEvent } from "react";

import { JobProgress } from "@/components/job-progress";
import { ForkContext, InvariantPanel, StepDetail, StepTimeline } from "@/components/lab";
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
  PageHeader,
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
  type SimulationCreateBody,
} from "@/lib/api/hooks";
import { useJobStream } from "@/lib/api/jobs";
import type { Chain, Pool, Scan, ScenarioRunSummary, Simulation } from "@/lib/api/models";
import { cn, formatDate, formatDuration, humanize } from "@/lib/format";

const STATUS_RANK: Record<string, number> = {
  unexpected_revert: 0,
  failed: 0,
  infra_error: 1,
  timed_out: 1,
  partial: 2,
  inconclusive: 2,
  passed: 3,
  cancelled: 4,
  skipped: 6,
  unsupported: 7,
};

type ScenarioId = NonNullable<SimulationCreateBody["scenarios"]>[number];

const WHOLE = /^\d{1,60}$/;

function RunForm({ scan, onStarted }: { scan: Scan; onStarted: (sim: Simulation) => void }) {
  const id = useId();
  const params = useSearchParams();
  const scenarios = useScenarios();
  const chains = useChains();
  const create = useCreateSimulation(scan.id);
  const preset = params.get("scenario");
  const [selected, setSelected] = useState<Set<string> | null>(preset ? new Set([preset]) : null);
  const [poolId, setPoolId] = useState(scan.pools[0]?.pool_id ?? "");
  const [adv, setAdv] = useState({ tick_lower: "", tick_upper: "", liquidity: "", amount0: "", amount1: "", swap_amount0: "", swap_amount1: "" });
  const [error, setError] = useState<string | null>(null);
  const all = scenarios.data?.map((s) => s.scenario_id) ?? [];
  const chosen = selected ?? new Set(all);
  const chain = chains.data?.find((c) => c.chain_id === scan.chain_id);
  const pool = scan.pools.find((p) => p.pool_id === poolId);

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
        Simulations fork the chain and exercise a real pool that uses this hook. This scan found no initialized pool.
      </EmptyState>
    );
  }

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-5">
      <KV
        items={[
          ["Hook", <Mono key="h" value={scan.hook_address} short />],
          ["Chain", chain ? `${chain.name} (${chain.chain_id})` : scan.chain_id],
          ["Fork block", scan.block_number ? `${scan.block_number} (pinned by the scan)` : "latest at run time"],
        ]}
      />
      <Field id={`${id}-pool`} label="Pool">
        <select id={`${id}-pool`} value={poolId} onChange={(e) => setPoolId(e.target.value)} className={`${inputClass} font-mono`}>
          {scan.pools.map((p) => (
            <option key={p.pool_id} value={p.pool_id}>
              {p.token0?.symbol ?? "?"}/{p.token1?.symbol ?? "?"} · {p.pool_id.slice(0, 18)}…
            </option>
          ))}
        </select>
      </Field>

      <fieldset className="flex flex-col gap-2">
        <legend className="mb-2 flex w-full items-center justify-between text-sm font-medium">
          Scenarios
          {scenarios.data ? (
            <span className="flex gap-2 text-xs font-normal">
              <button type="button" className="text-accent hover:underline" onClick={() => setSelected(new Set(all))}>
                all
              </button>
              <button type="button" className="text-muted hover:underline" onClick={() => setSelected(new Set())}>
                none
              </button>
            </span>
          ) : null}
        </legend>
        {scenarios.isPending ? <Spinner label="Loading scenarios…" /> : null}
        {scenarios.isError ? <ErrorState error={scenarios.error} onRetry={() => scenarios.refetch()} /> : null}
        <div className="grid gap-2">
          {scenarios.data?.map((s) => {
            const on = chosen.has(s.scenario_id);
            return (
              <label
                key={s.scenario_id}
                className={cn(
                  "flex cursor-pointer items-start gap-2.5 rounded-xl border p-3 transition-colors",
                  on ? "border-accent/60 bg-accent/10" : "border-line hover:bg-surface-2/60",
                )}
              >
                <input
                  type="checkbox"
                  className="mt-0.5 size-4 accent-[var(--color-accent)]"
                  checked={on}
                  onChange={(e) => {
                    const next = new Set(chosen);
                    if (e.target.checked) next.add(s.scenario_id);
                    else next.delete(s.scenario_id);
                    setSelected(next);
                  }}
                />
                <span className="min-w-0">
                  <span className="block text-sm font-medium">{s.title}</span>
                  <span className="mt-0.5 block text-xs text-muted">{s.description}</span>
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>

      <details className="rounded-xl border border-line p-3">
        <summary className="cursor-pointer text-sm text-muted hover:text-fg">Position & swap parameters (optional)</summary>
        <p className="mt-2 text-xs text-faint">
          Leave blank for the harness defaults: ±100 tick spacings around the current tick, 10 whole tokens per side
          sized with exact v4 math. Amounts are raw integer token units.
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
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
      <div>
        <Button type="submit" variant="primary" loading={create.isPending}>
          <Play aria-hidden="true" className="size-4" /> Run {chosen.size} scenario{chosen.size === 1 ? "" : "s"} on fork
        </Button>
      </div>
    </form>
  );
}

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
        <span className="font-medium">{humanize(summary.scenario_id)} was not run.</span> {summary.status_reason} This is
        a statement about applicability, not a result about the hook.
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
        <StatusBadge status={r.status} />
        <span className="text-sm text-muted">{r.status_reason}</span>
        <span className="ml-auto text-xs text-faint">
          forge {r.forge_status ?? "—"} · {formatDuration(r.duration_ms)}
          {meta.violations !== undefined ? ` · ${meta.violations} violation${meta.violations === 1 ? "" : "s"} recorded` : ""}
        </span>
      </div>
      {INFRA.has(r.status) ? (
        <Notice tone="warn">
          This is an infrastructure outcome ({humanize(r.status)}), not a finding about the hook. The scenario did not
          complete, so nothing can be concluded from it.
        </Notice>
      ) : null}
      {r.error ? <ErrorState title="Run error" error={new Error(String((r.error as { message?: string }).message ?? JSON.stringify(r.error)))} /> : null}

      {r.steps.length ? (
        <Card>
          <CardHeader title="Step timeline" description={`${r.steps.length} steps in execution order. Select one to inspect it.`} />
          <CardBody>
            <StepTimeline steps={r.steps} selected={step?.name ?? null} onSelect={(s) => setStepName(s.name)} />
          </CardBody>
        </Card>
      ) : (
        <Notice>The harness recorded no steps for this run.</Notice>
      )}

      {step ? <StepDetail run={r} step={step} pool={pool} hook={hook} /> : null}

      <InvariantPanel run={r} />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <ForkContext sim={sim} chain={chain} run={r} />
        <Card>
          <CardHeader title="Actors" description="Harness accounts. Privileged roles are impersonated inside the fork only; no keys are used." />
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
  if (sim.isPending) return <Spinner label="Loading simulation…" />;
  if (sim.isError) return <ErrorState error={sim.error} onRetry={() => sim.refetch()} />;
  const s = sim.data;
  const runs = s.runs ?? [];
  // Default to the most consequential run: failures before passes, unsupported last.
  const rank = (st: string) => STATUS_RANK[st] ?? 5;
  const current = runs.find((r) => r.id === runId) ?? [...runs].sort((a, b) => rank(a.status) - rank(b.status))[0];
  const pool = scan.pools.find((p) => p.pool_id === s.pool_id);
  const chain = chains.data?.find((c) => c.chain_id === s.chain_id);
  return (
    <div className="flex flex-col gap-5">
      {running && s.job_id ? (
        <Card>
          <CardBody>
            <JobProgress jobId={s.job_id} stream={stream} title="Simulation" />
          </CardBody>
        </Card>
      ) : null}
      {s.error ? <ErrorState title={`Simulation ${s.status}`} error={new Error(String((s.error as { message?: string }).message ?? JSON.stringify(s.error)))} /> : null}
      <Card>
        <CardHeader
          title="Simulation"
          description={`${formatDate(s.created_at)} · fork block ${s.fork_block ?? "?"}`}
          actions={
            <>
              <StatusBadge status={s.status} />
              {isTerminal(s.status) ? (
                <Button size="sm" asChild>
                  <Link href={`/app/lp?scan=${s.scan_id}&sim=${s.id}${s.pool_id ? `&pool=${s.pool_id}` : ""}`}>
                    <Gauge aria-hidden="true" className="size-3.5" /> Apply to LP position
                  </Link>
                </Button>
              ) : null}
            </>
          }
        />
        <CardBody className="flex flex-col gap-4">
          <div className="overflow-x-auto rounded-lg border border-line">
            <table className="w-full min-w-[640px] text-sm">
              <thead className="bg-surface text-left text-xs uppercase tracking-wide text-faint">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">Scenario</th>
                  <th scope="col" className="px-3 py-2 font-medium">Status</th>
                  <th scope="col" className="px-3 py-2 font-medium">Reason</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Duration</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.id} className={cn("cursor-pointer border-t border-line/60 hover:bg-surface-2/60", current?.id === r.id && "bg-surface-2")} onClick={() => setRunId(r.id)}>
                    <td className="px-3 py-2">
                      <button type="button" className="text-left text-accent hover:underline" onClick={() => setRunId(r.id)}>
                        {humanize(r.scenario_id)}
                      </button>
                    </td>
                    <td className="px-3 py-2">
                      <StatusBadge status={r.status} />
                    </td>
                    <td className="max-w-md px-3 py-2 text-xs text-muted">{r.status_reason}</td>
                    <td className="px-3 py-2 text-right text-xs tabular-nums text-muted">{formatDuration(r.duration_ms)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardBody>
      </Card>
      {current && current.status !== "queued" && current.status !== "running" ? (
        <section aria-label="Scenario run detail">
          <h2 className="mb-3 text-base font-semibold">{humanize(current.scenario_id)}</h2>
          <RunDetail key={current.id} sim={s} summary={current} pool={pool} chain={chain} hook={scan.hook_address} />
        </section>
      ) : null}
    </div>
  );
}

export function LabView() {
  const { id } = useParams<{ id: string }>();
  const scan = useScan(id);
  const sims = useSimulations(id, !!scan.data);
  const [simId, setSimId] = useState<string | null>(null);
  const current = simId ?? sims.data?.[0]?.id ?? null;
  const ordered = useMemo(() => sims.data ?? [], [sims.data]);

  if (scan.isPending) return <Spinner label="Loading scan…" />;
  if (scan.isError) return <ErrorState error={scan.error} onRetry={() => scan.refetch()} />;
  const s = scan.data;
  const ready = isTerminal(s.status) && s.status !== "failed";

  return (
    <>
      <PageHeader
        eyebrow="Adversarial Lab"
        title={s.contract?.contract_name ?? "Hook"}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Mono value={s.hook_address} />
            <span>
              Fork simulations run real Foundry tests against the PoolManager at the scan&apos;s pinned block. Statuses
              are forge outcomes, not predictions.
            </span>
          </span>
        }
        actions={
          <Button asChild>
            <Link href={`/app/scans/${s.id}`}>
              <ArrowLeft aria-hidden="true" className="size-4" /> Hook Intelligence
            </Link>
          </Button>
        }
      />
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[22rem_minmax(0,1fr)]">
        <div className="flex flex-col gap-6">
          <Card>
            <CardHeader title="Run simulation" />
            <CardBody>
              {ready ? (
                <RunForm scan={s} onStarted={(sim) => setSimId(sim.id)} />
              ) : (
                <Notice>{s.status === "failed" ? "The scan failed, so there is nothing to simulate." : "Waiting for the scan to finish…"}</Notice>
              )}
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="History" />
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
                      className={cn("flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-surface-2", current === sim.id && "bg-surface-2")}
                    >
                      <span className="text-muted">{formatDate(sim.created_at)}</span>
                      <StatusBadge status={sim.status} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
        <div className="min-w-0">
          {current ? (
            <SimulationDetail key={current} simId={current} scan={s} />
          ) : (
            <Card>
              <EmptyState title="No simulation selected" icon={<FlaskConical aria-hidden="true" className="size-8" />}>
                Choose scenarios and run them on a fork. Each scenario reports per-step expectations, decoded reverts, a
                call trace, and a command to reproduce it.
              </EmptyState>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}

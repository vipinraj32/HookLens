"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FlaskConical, Gauge, Play } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useId, useMemo, useState, type FormEvent } from "react";

import { JobProgress } from "@/components/job-progress";
import { RevertMessage, TraceTree } from "@/components/trace";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  CodeBlock,
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
  useCreateSimulation,
  useScan,
  useScenarioRun,
  useScenarios,
  useSimulation,
  useSimulations,
  type SimulationCreateBody,
} from "@/lib/api/hooks";
import { useJobStream } from "@/lib/api/jobs";
import type { Scan, ScenarioRun, ScenarioRunSummary, Simulation, Step } from "@/lib/api/models";
import { cn, formatDate, formatDuration, groupDecimal, humanize } from "@/lib/format";

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

function RunForm({ scan, onStarted }: { scan: Scan; onStarted: (sim: Simulation) => void }) {
  const id = useId();
  const scenarios = useScenarios();
  const create = useCreateSimulation(scan.id);
  const [selected, setSelected] = useState<Set<string> | null>(null);
  const [poolId, setPoolId] = useState(scan.pools[0]?.pool_id ?? "");
  const [adv, setAdv] = useState({ tick_lower: "", tick_upper: "", liquidity: "" });
  const [error, setError] = useState<string | null>(null);
  const all = scenarios.data?.map((s) => s.scenario_id) ?? [];
  const chosen = selected ?? new Set(all);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    const tl = adv.tick_lower.trim();
    const tu = adv.tick_upper.trim();
    const liq = adv.liquidity.trim();
    if ((tl === "") !== (tu === "")) return setError("Provide both ticks or neither.");
    if (tl && (!/^-?\d+$/.test(tl) || !/^-?\d+$/.test(tu))) return setError("Ticks must be integers.");
    if (tl && Number(tl) >= Number(tu)) return setError("tick_lower must be below tick_upper.");
    if (liq && !/^\d{1,39}$/.test(liq)) return setError("Liquidity must be a whole number (uint128).");
    if (chosen.size === 0) return setError("Select at least one scenario.");
    create.mutate(
      {
        pool_id: poolId || null,
        scenarios: [...chosen] as ScenarioId[],
        tick_lower: tl ? Number(tl) : null,
        tick_upper: tu ? Number(tu) : null,
        liquidity: liq || null,
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
        <legend className="mb-2 text-sm font-medium">Scenarios</legend>
        {scenarios.isPending ? <Spinner label="Loading scenarios…" /> : null}
        {scenarios.isError ? <ErrorState error={scenarios.error} onRetry={() => scenarios.refetch()} /> : null}
        {scenarios.data?.map((s) => (
          <label key={s.scenario_id} className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-line p-3 hover:bg-surface-2/60">
            <input
              type="checkbox"
              className="mt-0.5 size-4 accent-[var(--color-accent)]"
              checked={chosen.has(s.scenario_id)}
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
        ))}
      </fieldset>

      <details className="rounded-lg border border-line p-3">
        <summary className="cursor-pointer text-sm text-muted hover:text-fg">Position parameters (optional)</summary>
        <p className="mt-2 text-xs text-faint">
          By default the harness mints ±100 tick spacings around the current tick with 10 whole tokens per side, sized
          with exact v4 math.
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          {(["tick_lower", "tick_upper", "liquidity"] as const).map((k) => (
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
          <Play aria-hidden="true" className="size-4" /> Run on fork
        </Button>
      </div>
    </form>
  );
}

function StepsTable({ run, onSelect, selected }: { run: ScenarioRun; onSelect: (s: Step) => void; selected: string | null }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-line">
      <table className="w-full min-w-[780px] text-sm">
        <thead className="bg-surface text-left text-xs uppercase tracking-wide text-faint">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">Step</th>
            <th scope="col" className="px-3 py-2 font-medium">Phase · condition</th>
            <th scope="col" className="px-3 py-2 font-medium">LP expects</th>
            <th scope="col" className="px-3 py-2 font-medium">Observed</th>
            <th scope="col" className="px-3 py-2 font-medium">Status</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Δ token0 / token1</th>
          </tr>
        </thead>
        <tbody>
          {run.steps.map((s) => (
            <tr
              key={s.name}
              className={cn("cursor-pointer border-t border-line/60 hover:bg-surface-2/60", selected === s.name && "bg-surface-2")}
              onClick={() => onSelect(s)}
            >
              <td className="px-3 py-2">
                <button type="button" className="text-left font-mono text-xs text-accent hover:underline" onClick={() => onSelect(s)}>
                  {s.name}
                </button>
                {s.privileged ? <Badge className="ml-2 border-warn/40 text-warn">privileged</Badge> : null}
              </td>
              <td className="px-3 py-2 text-xs text-muted">
                {s.phase} · {s.condition}
              </td>
              <td className="px-3 py-2 text-xs">{s.lp_expectation}</td>
              <td className={cn("px-3 py-2 text-xs", s.observed === "revert" ? "text-bad" : "text-fg")}>{s.observed}</td>
              <td className="px-3 py-2">
                <StatusBadge status={s.step_status} />
              </td>
              <td className="px-3 py-2 text-right font-mono text-xs text-muted">
                {s.amount0 !== undefined ? `${groupDecimal(s.amount0)} / ${groupDecimal(s.amount1)}` : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RunDetail({ simId, summary }: { simId: string; summary: ScenarioRunSummary }) {
  const run = useScenarioRun(simId, summary.id);
  const [stepName, setStepName] = useState<string | null>(null);
  const step = run.data?.steps.find((s) => s.name === stepName) ?? run.data?.steps.find((s) => s.step_status === "unexpected_revert" || s.step_status === "failed") ?? null;

  if (summary.status === "unsupported" || summary.status === "skipped") {
    return (
      <Notice>
        <span className="font-medium">{humanize(summary.scenario_id)} was not run.</span> {summary.status_reason}
      </Notice>
    );
  }
  if (run.isPending) return <Spinner label="Loading run, steps and trace…" />;
  if (run.isError) return <ErrorState error={run.error} onRetry={() => run.refetch()} />;
  const r = run.data;
  const meta = r.result_meta as { actors?: Record<string, string>; block_number?: number; liquidity?: string; tick_lower?: number; tick_upper?: number; violations?: number };
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-2">
        <StatusBadge status={r.status} />
        <span className="text-sm text-muted">{r.status_reason}</span>
      </div>
      {r.error ? <ErrorState title="Run error" error={new Error(String((r.error as { message?: string }).message ?? JSON.stringify(r.error)))} /> : null}

      {r.steps.length ? <StepsTable run={r} selected={step?.name ?? null} onSelect={(s) => setStepName(s.name)} /> : null}

      {step ? (
        <Card>
          <CardHeader
            title={<span className="font-mono">{step.name}</span>}
            description={step.note}
            actions={<StatusBadge status={step.step_status} />}
          />
          <CardBody className="flex flex-col gap-4">
            {step.revert ? (
              <div className="rounded-lg border border-bad/30 bg-bad/5 p-3">
                <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-faint">Decoded revert</p>
                <RevertMessage revert={step.revert} />
              </div>
            ) : null}
            {step.revert_chain?.length ? (
              <div>
                <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-faint">Failing call path</p>
                <ol className="flex flex-col gap-1 font-mono text-xs">
                  {step.revert_chain.map((f, i, all) => (
                    <li key={f.idx} className="flex flex-wrap gap-2" style={{ paddingLeft: i * 12 }}>
                      <span className="text-accent">{f.label ?? f.address}</span>
                      <span>{f.function?.split("(")[0] ?? f.selector}</span>
                      {i === all.length - 1 && f.revert?.message ? <span className="text-bad">→ {f.revert.message}</span> : null}
                    </li>
                  ))}
                </ol>
              </div>
            ) : null}
            <div>
              <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-faint">Call trace</p>
              <TraceTree trace={r.trace} roots={step.trace_nodes ?? r.trace.steps?.[step.name] ?? []} />
            </div>
            <KV
              items={[
                ["Gas used", step.gas_used?.toLocaleString() ?? "—"],
                ["Block timestamp", step.block_timestamp ?? "—"],
                ["Raw revert data", step.revert_data && step.revert_data !== "0x" ? <Mono key="rd" value={step.revert_data} short /> : "—"],
              ]}
            />
          </CardBody>
        </Card>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Execution" />
          <CardBody>
            <KV
              items={[
                ["Forge status", r.forge_status ?? "—"],
                ["Duration", formatDuration(r.duration_ms)],
                ["Fork block", meta.block_number ?? "—"],
                ["Position", meta.tick_lower !== undefined ? `[${meta.tick_lower}, ${meta.tick_upper}) L=${groupDecimal(meta.liquidity)}` : "—"],
                ["Violations recorded by harness", meta.violations ?? "—"],
                ["Trace", r.trace.total_nodes !== undefined ? `${r.trace.total_nodes} nodes, ${r.trace.pruned_cheatcode_calls ?? 0} cheatcode calls pruned${r.trace.truncated ? ", truncated" : ""}` : "—"],
              ]}
            />
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Actors" description="Harness accounts; the owner is impersonated inside the fork only." />
          <CardBody>
            <KV items={Object.entries(meta.actors ?? {}).map(([k, v]) => [k, <Mono key={k} value={v} />])} />
          </CardBody>
        </Card>
      </div>
      <div>
        <p className="mb-1.5 text-sm font-medium">Reproduce locally</p>
        <p className="mb-2 text-xs text-muted">
          Replace the placeholder with an archive RPC URL for this chain (or a local Anvil URL). HookLens never embeds
          RPC credentials in commands.
        </p>
        <CodeBlock code={r.repro_command} />
      </div>
    </div>
  );
}

function SimulationDetail({ simId }: { simId: string }) {
  const qc = useQueryClient();
  const sim = useSimulation(simId);
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
  const harness = s.spec.harness as { version?: string; digest?: string } | undefined;
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
          <KV
            items={[
              ["Pool", <Mono key="p" value={s.pool_id} short />],
              ["Fork block hash", <Mono key="b" value={s.fork_block_hash} short />],
              ["Harness", `${harness?.version ?? s.harness_version ?? "—"}${harness?.digest ? ` · ${harness.digest.slice(0, 19)}…` : ""}`],
            ]}
          />
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
          <RunDetail key={current.id} simId={s.id} summary={current} />
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
        eyebrow="Adversarial lab"
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
              <ArrowLeft aria-hidden="true" className="size-4" /> Hook intelligence
            </Link>
          </Button>
        }
      />
      <div className="grid gap-6 xl:grid-cols-[22rem_minmax(0,1fr)]">
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
            <SimulationDetail key={current} simId={current} />
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

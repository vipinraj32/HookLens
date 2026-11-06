"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Calculator } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useId, useMemo } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { LpVsHoldChart } from "@/components/lp-chart";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorState,
  Field,
  Notice,
  PageHeader,
  Spinner,
  StatusBadge,
  TagBadge,
  inputClass,
} from "@/components/ui";
import { isTerminal, useCompare, useScan, useScans, useSimulations, type CompareBody } from "@/lib/api/hooks";
import { RangeBar } from "@/components/range-bar";
import { ScanWorkflow } from "@/components/workflow";
import type { Compare, Pool, Tagged } from "@/lib/api/models";
import { formatDate, groupDecimal, humanize } from "@/lib/format";

const DEC = /^\d{1,40}(\.\d{1,40})?$/;
const optDec = (msg: string) => z.string().trim().refine((v) => v === "" || DEC.test(v), msg);

const schema = z
  .object({
    pool_id: z.string().min(1, "Select a pool."),
    simulation_id: z.string(),
    mode: z.enum(["price", "tick"]),
    orientation: z.enum(["token1_per_token0", "token0_per_token1"]),
    lower: z.string().trim().min(1, "Required."),
    upper: z.string().trim().min(1, "Required."),
    amount0: optDec("Enter a decimal amount."),
    amount1: optDec("Enter a decimal amount."),
    moves: z
      .string()
      .trim()
      .refine(
        (v) => v === "" || v.split(",").every((x) => /^-?\d+(\.\d+)?$/.test(x.trim()) && Number(x) > -100 && Number(x) <= 10000),
        "Comma-separated percentages greater than -100, e.g. -50, -20, 20, 100.",
      ),
  })
  .superRefine((v, ctx) => {
    if (v.mode === "tick") {
      for (const k of ["lower", "upper"] as const)
        if (!/^-?\d+$/.test(v[k])) ctx.addIssue({ code: "custom", path: [k], message: "Ticks are integers." });
      if (Number(v.lower) >= Number(v.upper)) ctx.addIssue({ code: "custom", path: ["upper"], message: "Upper tick must be above lower." });
    } else {
      for (const k of ["lower", "upper"] as const)
        if (!DEC.test(v[k]) || Number(v[k]) <= 0) ctx.addIssue({ code: "custom", path: [k], message: "Enter a positive price." });
      if (DEC.test(v.lower) && DEC.test(v.upper) && Number(v.lower) >= Number(v.upper))
        ctx.addIssue({ code: "custom", path: ["upper"], message: "Upper price must be above lower." });
    }
    if (!v.amount0 && !v.amount1) ctx.addIssue({ code: "custom", path: ["amount0"], message: "Provide at least one token amount." });
  });
type FormValues = z.infer<typeof schema>;

function sym(pool: Pool | undefined, i: 0 | 1) {
  return (i === 0 ? pool?.token0?.symbol : pool?.token1?.symbol) ?? `token${i}`;
}

function TaggedValue({ label, t, unit }: { label: string; t: Tagged | undefined; unit?: string }) {
  if (!t) return null;
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-line bg-surface px-4 py-3">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs uppercase tracking-wide text-faint">{label}</span>
        <TagBadge tag={t.tag} />
      </div>
      <span className="font-mono text-sm text-fg">
        {t.value === null ? <span className="text-faint">unavailable</span> : typeof t.value === "number" ? t.value : /^-?\d/.test(t.value) ? groupDecimal(t.value, 8) : t.value}
        {t.value !== null && unit ? <span className="ml-1 text-muted">{unit}</span> : null}
      </span>
      <span className="text-[11px] leading-snug text-faint">{t.basis}</span>
    </div>
  );
}

function Results({ r }: { r: Compare }) {
  const t0 = r.pool.token0.symbol ?? "token0";
  const t1 = r.pool.token1.symbol ?? "token1";
  const b = r.baseline;
  const fx = r.simulation_effects;
  const label = (t: Tagged | undefined) =>
    t && t.value !== null && typeof t.value === "string" && /^-?\d/.test(t.value) ? `${groupDecimal(t.value, 6)} ${t1}` : undefined;
  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader
          title="Baseline position"
          description={`Ticks [${r.position.tick_lower}, ${r.position.tick_upper}) · L = ${groupDecimal(r.position.liquidity)} · block ${r.pool.block_number ?? "?"}`}
          actions={<Badge className="font-mono text-faint">{r.calculation_version}</Badge>}
        />
        <CardBody className="flex flex-col gap-4">
          <RangeBar
            tickLower={r.position.tick_lower}
            tickUpper={r.position.tick_upper}
            currentTick={r.pool.state.tick}
            lowerLabel={label(b.price_lower)}
            upperLabel={label(b.price_upper)}
            currentLabel={label(b.price) ? `price ${label(b.price)} per ${t0}` : undefined}
          />
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <TaggedValue label="Range state" t={b.range_state} />
            <TaggedValue label={`Price (${t1} per ${t0})`} t={b.price} />
            <TaggedValue label={`Price (${t0} per ${t1})`} t={b.price_inverted} />
            <TaggedValue label="Range lower" t={b.price_lower} unit={t1} />
            <TaggedValue label="Range upper" t={b.price_upper} unit={t1} />
            <TaggedValue label="Deposit token0" t={b.deposit_amount0} unit={t0} />
            <TaggedValue label="Deposit token1" t={b.deposit_amount1} unit={t1} />
            <TaggedValue label="Value" t={b.value_in_token1} unit={t1} />
            <TaggedValue label="Share of active liquidity (%)" t={b.share_of_active_liquidity} />
            <TaggedValue label="Fee income" t={b.fee_income} />
          </div>
          {r.notes.length ? (
            <ul className="list-disc pl-5 text-xs text-muted">
              {r.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          ) : null}
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Price scenarios" description="Hypothetical instantaneous moves of the pool price." actions={<TagBadge tag="hypothetical" />} />
        <CardBody className="flex flex-col gap-4">
          <LpVsHoldChart data={r.price_scenarios} unit={t1} />
          <div className="overflow-x-auto rounded-lg border border-line">
            <table className="w-full min-w-[720px] text-sm">
              <caption className="sr-only">LP value vs hold value per price move</caption>
              <thead className="bg-surface text-left text-xs uppercase tracking-wide text-faint">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">Move</th>
                  <th scope="col" className="px-3 py-2 font-medium">Price</th>
                  <th scope="col" className="px-3 py-2 font-medium">Range</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">{t0}</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">{t1}</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">LP value</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Hold value</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">vs hold</th>
                </tr>
              </thead>
              <tbody className="font-mono text-xs">
                {[...r.price_scenarios]
                  .sort((a, b2) => a.price_move - b2.price_move)
                  .map((p) => (
                    <tr key={p.price_move} className="border-t border-line/60">
                      <td className="px-3 py-2">{`${p.price_move > 0 ? "+" : ""}${Math.round(p.price_move * 100)}%`}</td>
                      <td className="px-3 py-2">{groupDecimal(p.price, 4)}</td>
                      <td className="px-3 py-2 font-sans text-muted">{p.range_state}</td>
                      <td className="px-3 py-2 text-right">{groupDecimal(p.amount0)}</td>
                      <td className="px-3 py-2 text-right">{groupDecimal(p.amount1)}</td>
                      <td className="px-3 py-2 text-right">{groupDecimal(p.lp_value_token1)}</td>
                      <td className="px-3 py-2 text-right">{groupDecimal(p.hold_value_token1)}</td>
                      <td className="px-3 py-2 text-right">
                        {groupDecimal(p.divergence_token1)} {p.divergence_pct ? `(${p.divergence_pct}%)` : ""}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </CardBody>
      </Card>

      <Card>
        <CardHeader title="Measured hook effects" description="From the selected fork simulation." actions={<TagBadge tag={fx?.tag === "unavailable" || !fx ? "unavailable" : "measured"} />} />
        <CardBody className="flex flex-col gap-4">
          {!fx || fx.tag === "unavailable" ? (
            <p className="text-sm text-muted">{fx?.reason ?? "No simulation selected. Run the Adversarial Lab to measure effects."}</p>
          ) : (
            <>
              <p className="flex flex-wrap items-center gap-2 text-xs text-muted">
                Simulation <StatusBadge status={fx.status ?? "unknown"} /> at fork block {fx.fork_block ?? "?"}
                {fx.simulated_position ? (
                  <span>
                    · simulated range [{fx.simulated_position.tick_lower}, {fx.simulated_position.tick_upper})
                  </span>
                ) : null}
              </p>
              {fx.same_range_as_simulation === false ? (
                <Notice tone="warn">
                  The simulation used a different range and liquidity than this position. Whether an operation reverts
                  transfers to your position; measured token amounts apply only qualitatively.
                </Notice>
              ) : null}
              {fx.withdrawal_blocked_under?.length ? (
                <div className="flex flex-col gap-2">
                  <h3 className="text-sm font-semibold text-bad">Withdrawal blocked under {fx.withdrawal_blocked_under.length} condition(s)</h3>
                  <ul className="flex flex-col gap-2">
                    {fx.withdrawal_blocked_under.map((w) => (
                      <li key={`${w.scenario}-${w.step}`} className="rounded-lg border border-bad/30 bg-bad/5 p-3 text-sm">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="font-medium">{humanize(w.condition)}</span>
                          <span className="font-mono text-xs text-faint">
                            {w.scenario}/{w.step}
                          </span>
                          <TagBadge tag={w.tag} />
                        </div>
                        {w.revert ? <p className="mt-1 break-words text-xs text-bad">{w.revert}</p> : null}
                        {w.position_value_unwithdrawable_token1 ? (
                          <p className="mt-1 text-xs text-muted">
                            Value not withdrawable while this holds:{" "}
                            <span className="font-mono text-fg">
                              {groupDecimal(w.position_value_unwithdrawable_token1)} {t1}
                            </span>
                            . {w.value_basis}
                          </p>
                        ) : null}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <p className="text-sm text-ok">No tested condition blocked liquidity removal in this simulation.</p>
              )}
              {fx.withdrawal_succeeded_under?.length ? (
                <p className="text-xs text-muted">
                  Removal succeeded under: {fx.withdrawal_succeeded_under.map(humanize).join(", ")}
                </p>
              ) : null}
              <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
                {fx.fee ? (
                  <div className="rounded-lg border border-line p-3 text-sm">
                    <p className="text-xs uppercase tracking-wide text-faint">LP fee</p>
                    <p className="mt-1">
                      Baseline {fx.fee.baseline_fee_pips ?? "—"} pips → after owner change{" "}
                      <span className="font-mono">{fx.fee.max_fee_after_owner_change_pips ?? "—"}</span> pips
                    </p>
                    <p className="mt-1 text-xs text-faint">{fx.fee.basis}</p>
                  </div>
                ) : null}
                {fx.round_trip ? (
                  <div className="rounded-lg border border-line p-3 text-sm">
                    <p className="text-xs uppercase tracking-wide text-faint">Simulated round trip</p>
                    <p className="mt-1 font-mono text-xs">
                      Δ{t0} {groupDecimal(String(fx.round_trip.net_amount0 ?? ""), 12)} · Δ{t1}{" "}
                      {groupDecimal(String(fx.round_trip.net_amount1 ?? ""), 12)}
                    </p>
                    <p className="mt-1 text-xs text-faint">{String(fx.round_trip.description ?? "")}</p>
                  </div>
                ) : null}
                {fx.accounting ? (
                  <div className="rounded-lg border border-line p-3 text-sm">
                    <p className="text-xs uppercase tracking-wide text-faint">Accounting invariants</p>
                    <p className="mt-1">
                      <StatusBadge status={String(fx.accounting.status ?? "unknown")} />
                    </p>
                    {Array.isArray(fx.accounting.violations) && fx.accounting.violations.length ? (
                      <p className="mt-1 text-xs text-bad">Violations: {(fx.accounting.violations as string[]).join(", ")}</p>
                    ) : null}
                  </div>
                ) : null}
              </div>
            </>
          )}
        </CardBody>
      </Card>
      <p className="text-xs text-faint">{r.disclaimer}</p>
    </div>
  );
}

function LpForm({ scanId, initialPool, initialSim }: { scanId: string; initialPool: string | null; initialSim: string | null }) {
  const id = useId();
  const scan = useScan(scanId);
  const sims = useSimulations(scanId, !!scan.data);
  const compare = useCompare();
  const pools = useMemo(() => scan.data?.pools ?? [], [scan.data]);
  const done = (sims.data ?? []).filter((s) => isTerminal(s.status) && s.status !== "failed");

  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    mode: "onTouched",
    defaultValues: {
      pool_id: initialPool ?? "",
      simulation_id: initialSim ?? "",
      mode: "price",
      orientation: "token1_per_token0",
      lower: "",
      upper: "",
      amount0: "",
      amount1: "",
      moves: "-50, -20, -10, 10, 20, 50, 100",
    },
  });
  const { setValue, getValues } = form;
  useEffect(() => {
    if (!getValues("pool_id") && pools[0]) setValue("pool_id", pools[0].pool_id);
  }, [pools, getValues, setValue]);
  useEffect(() => {
    // The <select> has no options until the list loads, so a value set at mount is lost in the DOM;
    // re-apply the requested simulation (or default to the newest) once the options exist.
    if (initialSim && done.some((s) => s.id === initialSim)) setValue("simulation_id", initialSim);
    else if (!getValues("simulation_id") && !initialSim && done[0]) setValue("simulation_id", done[0].id);
    // only when the list first loads
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [done.length]);

  const [poolId, mode, orientation] = useWatch({ control: form.control, name: ["pool_id", "mode", "orientation"] });
  const pool = pools.find((p) => p.pool_id === poolId);
  const s0 = sym(pool, 0);
  const s1 = sym(pool, 1);
  const quote = orientation === "token1_per_token0" ? `${s1} per ${s0}` : `${s0} per ${s1}`;

  const onSubmit = form.handleSubmit((v) => {
    const body: CompareBody = {
      scan_id: scanId,
      pool_id: v.pool_id,
      simulation_id: v.simulation_id || null,
      amount0: v.amount0 || null,
      amount1: v.amount1 || null,
      price_orientation: v.orientation,
      price_moves: v.moves ? v.moves.split(",").map((x) => Number(x.trim()) / 100) : null,
      ...(v.mode === "tick"
        ? { tick_lower: Number(v.lower), tick_upper: Number(v.upper) }
        : { price_lower: v.lower, price_upper: v.upper }),
    };
    compare.mutate(body);
  });

  if (scan.isPending) return <Spinner label="Loading scan…" />;
  if (scan.isError) return <ErrorState error={scan.error} onRetry={() => scan.refetch()} />;
  if (pools.length === 0) return <EmptyState title="This scan found no pools">LP exposure needs an initialized pool that uses the hook.</EmptyState>;

  const err = form.formState.errors;
  const f = (n: string) => `${id}-${n}`;
  const desc = (n: keyof FormValues, hint = false) => [hint ? `${f(n)}-hint` : "", err[n] ? `${f(n)}-error` : ""].filter(Boolean).join(" ") || undefined;
  const state = pool?.state;

  return (
    <div className="grid grid-cols-1 gap-6 xl:grid-cols-[24rem_minmax(0,1fr)]">
      <Card className="h-fit">
        <CardHeader title="Position" description="Every amount is computed with exact integer v4 math." />
        <CardBody>
          <form noValidate onSubmit={onSubmit} className="flex flex-col gap-4">
            <Field id={f("pool")} label="Pool" error={err.pool_id?.message}>
              <select id={f("pool")} className={`${inputClass} font-mono`} {...form.register("pool_id")}>
                {pools.map((p) => (
                  <option key={p.pool_id} value={p.pool_id}>
                    {sym(p, 0)}/{sym(p, 1)} · {p.fee} pips · {p.pool_id.slice(0, 12)}…
                  </option>
                ))}
              </select>
            </Field>
            {state?.initialized ? (
              <p className="-mt-2 text-xs text-faint">
                Current tick {state.tick} · spacing {pool?.tick_spacing} · read at block {state.block_number}
              </p>
            ) : null}

            <Field id={f("sim")} label="Apply simulation" hint="Measured effects from a completed Adversarial Lab run.">
              <select id={f("sim")} className={inputClass} aria-describedby={`${f("sim")}-hint`} {...form.register("simulation_id")}>
                <option value="">None</option>
                {done.map((s) => (
                  <option key={s.id} value={s.id}>
                    {formatDate(s.created_at)} · {s.status}
                  </option>
                ))}
              </select>
            </Field>

            <fieldset className="flex flex-col gap-2">
              <legend className="mb-1 text-sm font-medium">Range as</legend>
              <div className="flex gap-4 text-sm">
                <label className="flex items-center gap-2">
                  <input type="radio" value="price" className="accent-[var(--color-accent)]" {...form.register("mode")} /> Prices
                </label>
                <label className="flex items-center gap-2">
                  <input type="radio" value="tick" className="accent-[var(--color-accent)]" {...form.register("mode")} /> Ticks
                </label>
              </div>
            </fieldset>

            {mode === "price" ? (
              <Field id={f("orient")} label="Quote prices as">
                <select id={f("orient")} className={inputClass} {...form.register("orientation")}>
                  <option value="token1_per_token0">
                    {s1} per {s0}
                  </option>
                  <option value="token0_per_token1">
                    {s0} per {s1}
                  </option>
                </select>
              </Field>
            ) : null}

            <div className="grid grid-cols-2 gap-3">
              {(["lower", "upper"] as const).map((k) => (
                <Field key={k} id={f(k)} label={`${humanize(k)} ${mode === "price" ? "price" : "tick"}`} hint={mode === "price" ? quote : `multiple of ${pool?.tick_spacing ?? "?"}`} error={err[k]?.message}>
                  <input
                    id={f(k)}
                    className={`${inputClass} font-mono`}
                    inputMode="decimal"
                    autoComplete="off"
                    aria-invalid={err[k] ? true : undefined}
                    aria-describedby={desc(k, true)}
                    {...form.register(k)}
                  />
                </Field>
              ))}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field id={f("a0")} label={`${s0} amount`} error={err.amount0?.message}>
                <input id={f("a0")} className={`${inputClass} font-mono`} inputMode="decimal" autoComplete="off" aria-invalid={err.amount0 ? true : undefined} aria-describedby={desc("amount0")} {...form.register("amount0")} />
              </Field>
              <Field id={f("a1")} label={`${s1} amount`} error={err.amount1?.message}>
                <input id={f("a1")} className={`${inputClass} font-mono`} inputMode="decimal" autoComplete="off" aria-invalid={err.amount1 ? true : undefined} aria-describedby={desc("amount1")} {...form.register("amount1")} />
              </Field>
            </div>
            <p className="-mt-2 text-xs text-faint">
              For a range around the current price, one token is enough: HookLens sizes the position from it and shows the other token needed. With both, the scarcer one decides. Out-of-range positions hold one token only.
            </p>
            <Field id={f("moves")} label="Price moves (%)" hint="Hypothetical instant moves to compare against holding." error={err.moves?.message}>
              <input id={f("moves")} className={`${inputClass} font-mono`} autoComplete="off" aria-invalid={err.moves ? true : undefined} aria-describedby={desc("moves", true)} {...form.register("moves")} />
            </Field>
            <div>
              <Button type="submit" variant="primary" loading={compare.isPending}>
                <Calculator aria-hidden="true" className="size-4" /> Compute exposure
              </Button>
            </div>
          </form>
        </CardBody>
      </Card>
      <div className="min-w-0">
        {compare.isError ? <ErrorState error={compare.error} title="Could not compute this position" /> : null}
        {compare.data ? <Results r={compare.data} /> : !compare.isError ? (
          <Card>
            <EmptyState title="Describe a position">
              Enter a range and token amounts. HookLens reads the pool at the scan&apos;s pinned block and, if you pick a
              simulation, overlays what was measured on the fork.
            </EmptyState>
          </Card>
        ) : null}
      </div>
    </div>
  );
}

function ScanPicker() {
  const router = useRouter();
  const scans = useScans(0, 50);
  if (scans.isPending) return <Spinner label="Loading scans…" />;
  if (scans.isError) return <ErrorState error={scans.error} onRetry={() => scans.refetch()} />;
  const usable = scans.data.items.filter((s) => isTerminal(s.status) && s.status !== "failed");
  if (usable.length === 0) {
    return (
      <Card>
        <EmptyState
          title="No completed scans"
          action={
            <Button variant="primary" onClick={() => router.push("/app/scan")}>
              Scan a hook
            </Button>
          }
        >
          LP exposure is computed against a pool discovered by a scan.
        </EmptyState>
      </Card>
    );
  }
  return (
    <Card>
      <CardHeader title="Choose a scan" />
      <ul className="flex flex-col p-2">
        {usable.map((s) => (
          <li key={s.id}>
            <button type="button" onClick={() => router.push(`/app/lp?scan=${s.id}`)} className="flex w-full flex-wrap items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm hover:bg-surface-2">
              <span className="font-mono text-accent">{s.hook_address}</span>
              <span className="text-xs text-muted">chain {s.chain_id}</span>
              <span className="ml-auto text-xs text-faint">{formatDate(s.created_at)}</span>
            </button>
          </li>
        ))}
      </ul>
    </Card>
  );
}

const TAG_LEGEND: [string, string, string][] = [
  ["on-chain", "Measured", "Read from the chain at the scan's pinned block, or derived from it with exact v4 math."],
  ["measured", "Measured", "Observed in an executed fork simulation that you selected."],
  ["hypothetical", "Hypothetical", "Depends on your inputs or a stated assumption (your range, price moves)."],
  ["unavailable", "Unavailable", "Cannot be computed honestly from the data available; the reason is shown."],
];

function TagLegend() {
  return (
    <dl aria-label="How LP figures are labelled" className="mb-6 grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
      {TAG_LEGEND.map(([tag, kind, meaning]) => (
        <div key={tag} className="rounded-xl border border-line bg-surface px-3.5 py-3">
          <dt className="flex items-center gap-2 text-xs font-medium text-fg">
            <TagBadge tag={tag} /> <span className="text-faint">{kind}</span>
          </dt>
          <dd className="mt-1.5 text-xs text-muted">{meaning}</dd>
        </div>
      ))}
    </dl>
  );
}

function LpWorkflow({ scanId }: { scanId: string }) {
  const scan = useScan(scanId);
  return scan.data ? <ScanWorkflow scan={scan.data} current="lp" /> : null;
}

export function LpView() {
  const params = useSearchParams();
  const scanId = params.get("scan");
  return (
    <>
      {scanId ? <LpWorkflow scanId={scanId} /> : null}
      <PageHeader
        eyebrow="LP exposure"
        title="What is this position exposed to?"
        description="Baseline figures are exact v4 math on on-chain state. Price scenarios are hypothetical. Hook effects are measured only when you apply a simulation. Fee income is not forecast."
      />
      <TagLegend />
      {scanId ? <LpForm key={scanId} scanId={scanId} initialPool={params.get("pool")} initialSim={params.get("sim")} /> : <ScanPicker />}
    </>
  );
}

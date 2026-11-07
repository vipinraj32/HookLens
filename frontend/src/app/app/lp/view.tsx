"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Calculator, RotateCw } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useId, useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { LpVsHoldChart } from "@/components/lp-chart";
import { RangeBar } from "@/components/range-bar";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorState,
  Field,
  InfoTip,
  Notice,
  PageHeader,
  Spinner,
  StatusBadge,
  TagBadge,
  inputClass,
} from "@/components/ui";
import {
  LIVE_REFRESH_MS,
  isTerminal,
  useCompare,
  useLivePool,
  useRefreshLivePool,
  useScan,
  useScans,
  useSimulations,
  type CompareBody,
} from "@/lib/api/hooks";
import type { Compare, DataSource, Pool, SimulationEffects, Tagged, WithdrawalOutcome } from "@/lib/api/models";
import { cn, formatDate, groupDecimal, humanize } from "@/lib/format";

const DEC = /^\d{1,40}(\.\d{1,40})?$/;
const optDec = (msg: string) => z.string().trim().refine((v) => v === "" || DEC.test(v), msg);

const schema = z
  .object({
    pool_id: z.string().min(1, "Select a pool."),
    simulation_id: z.string(),
    state_source: z.enum(["live", "scan"]),
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

/** Seconds since a unix timestamp, re-rendering every second. */
function useAge(unixSeconds: number | null | undefined) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  if (unixSeconds == null) return null;
  return Math.max(0, Math.round(now / 1000 - unixSeconds));
}

function ago(s: number | null) {
  if (s === null) return "time unknown";
  if (s < 90) return `${s}s ago`;
  if (s < 5400) return `${Math.round(s / 60)}m ago`;
  return `${Math.round(s / 3600)}h ago`;
}

// ---------------------------------------------------------------- live state

function LiveStateBar({ scanId, pool }: { scanId: string; pool: Pool | undefined }) {
  const live = useLivePool(scanId, pool?.pool_id);
  const refresh = useRefreshLivePool(scanId, pool?.pool_id);
  const d = live.data;
  const age = useAge(d?.block_timestamp);
  const busy = live.isFetching || refresh.isPending;
  const t0 = sym(pool, 0);
  const t1 = sym(pool, 1);

  return (
    <section aria-label="Live pool state" className="mb-6 rounded-xl border border-line bg-surface">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 text-sm">
        <span className="inline-flex items-center gap-2 font-medium">
          <span
            aria-hidden="true"
            className={cn("size-2 rounded-full", live.isError ? "bg-warn" : d ? "bg-ok" : "bg-line-strong", busy && d && "animate-pulse")}
          />
          {live.isError ? "Live data unavailable" : d ? "Live" : "Reading chain…"}
        </span>
        {d ? (
          <>
            <span className="text-muted">{d.chain_name}</span>
            <span className="text-muted">
              block <span className="font-mono tabular-nums text-fg">{d.block_number.toLocaleString()}</span>
            </span>
            <span className="text-faint" title={d.block_time ?? undefined}>
              {ago(age)}
            </span>
            {d.scan_block_number ? (
              <span className="text-faint">
                scan pinned {d.scan_block_number.toLocaleString()} (+{(d.block_number - d.scan_block_number).toLocaleString()})
              </span>
            ) : null}
          </>
        ) : null}
        <span className="ml-auto inline-flex items-center gap-2 text-xs text-faint">
          {LIVE_REFRESH_MS ? `auto ${Math.round(LIVE_REFRESH_MS / 1000)}s` : "manual"}
          <InfoTip label="About live data" align="end">
            Read from the PoolManager at the chain&apos;s latest block through the server&apos;s RPC. Polls while this tab is
            visible; the server caches state per block. Never replaced by older data on failure.
          </InfoTip>
          <Button size="sm" onClick={() => refresh.mutate()} disabled={!pool || busy} aria-label="Refresh live pool state">
            <RotateCw aria-hidden="true" className={cn("size-3.5", busy && "animate-spin")} /> Refresh
          </Button>
        </span>
      </div>
      {d ? (
        <dl className="grid grid-cols-2 gap-px border-t border-line bg-line text-sm sm:grid-cols-4">
          {[
            [`Price (${t1}/${t0})`, d.price ? groupDecimal(d.price.token1_per_token0, 8) : "—"],
            ["Tick", d.state.tick ?? "—"],
            ["Active liquidity", d.state.liquidity ? groupDecimal(d.state.liquidity) : "—"],
            ["LP fee", d.state.lp_fee !== undefined ? `${d.state.lp_fee} pips` : "—"],
          ].map(([k, v]) => (
            <div key={String(k)} className="min-w-0 bg-surface px-4 py-2.5">
              <dt className="text-[11px] uppercase tracking-wide text-faint">{k}</dt>
              <dd className="mt-0.5 truncate font-mono tabular-nums">{v}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {live.isError ? (
        <p role="alert" className="border-t border-line px-4 py-2.5 text-xs text-warn">
          {live.error.message} No older data is substituted.
        </p>
      ) : null}
    </section>
  );
}

// ---------------------------------------------------------------- results

function TaggedValue({ label, t, unit }: { label: string; t: Tagged | undefined; unit?: string }) {
  if (!t) return null;
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-line bg-surface px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1">
        <span className="inline-flex min-w-0 items-center gap-0.5 text-xs uppercase tracking-wide text-faint">
          {label}
          <InfoTip label={`How ${label} is derived`} align="start">
            {t.basis}
          </InfoTip>
        </span>
        <TagBadge tag={t.tag} />
      </div>
      <span className="break-all font-mono text-sm text-fg">
        {t.value === null ? <span className="text-faint">unavailable</span> : typeof t.value === "number" ? t.value : /^-?\d/.test(t.value) ? groupDecimal(t.value, 8) : t.value}
        {t.value !== null && unit ? <span className="ml-1 text-muted">{unit}</span> : null}
      </span>
    </div>
  );
}

function SourceLine({ src }: { src: DataSource | undefined }) {
  const age = useAge(src?.block_timestamp);
  if (!src) return null;
  const live = src.source === "live";
  return (
    <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted">
      <TagBadge tag={live ? "live" : "historical"} />
      <span>
        block <span className="font-mono text-fg">{src.block_number?.toLocaleString() ?? "?"}</span>
      </span>
      {src.block_hash ? <span className="font-mono text-faint">{src.block_hash.slice(0, 10)}…</span> : null}
      {live ? <span className="text-faint">{ago(age)}</span> : <span className="text-faint">scan snapshot</span>}
      {src.fetched_at ? <span className="text-faint">fetched {formatDate(src.fetched_at)}</span> : null}
    </p>
  );
}

const WITHDRAWAL_LABEL: Record<string, { label: string; tone: string }> = {
  completed: { label: "Withdrawal completed", tone: "text-ok border-ok/40 bg-ok/10" },
  blocked: { label: "Withdrawal blocked (position existed)", tone: "text-bad border-bad/40 bg-bad/10" },
  not_tested: { label: "Withdrawal not tested", tone: "text-muted border-line bg-surface-2" },
  unsupported: { label: "Withdrawal test unsupported", tone: "text-faint border-line bg-surface-2" },
  execution_error: { label: "Withdrawal test execution error", tone: "text-warn border-warn/40 bg-warn/10" },
};

const CREATION_LABEL: Record<string, { label: string; tone: string }> = {
  created: { label: "Position created", tone: "text-ok border-ok/40 bg-ok/10" },
  rejected: { label: "Position creation rejected", tone: "text-bad border-bad/40 bg-bad/10" },
  not_attempted: { label: "No position attempted", tone: "text-faint border-line bg-surface-2" },
};

function HistoricalSimulation({ fx, t0, t1 }: { fx: SimulationEffects | null | undefined; t0: string; t1: string }) {
  if (!fx || fx.tag === "unavailable") {
    return (
      <Card>
        <CardHeader title="Historical simulation" actions={<TagBadge tag="unavailable" />} />
        <CardBody>
          <p className="text-sm text-muted">{fx?.reason ?? "No simulation applied."}</p>
        </CardBody>
      </Card>
    );
  }
  const creation = fx.position_creation;
  const wd = fx.withdrawal;
  const notTested: WithdrawalOutcome[] = fx.withdrawal_not_tested ?? [];
  const gap = fx.blocks_since_simulation;
  return (
    <Card>
      <CardHeader
        title="Historical simulation"
        description={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            <StatusBadge status={fx.status ?? "unknown"} />
            <span>
              fork block <span className="font-mono text-fg">{fx.fork_block?.toLocaleString() ?? "?"}</span>
            </span>
            {gap !== null && gap !== undefined ? (
              <span>
                {gap >= 0 ? `${gap.toLocaleString()} blocks before` : `${(-gap).toLocaleString()} blocks after`} the state above
              </span>
            ) : null}
          </span>
        }
        actions={<TagBadge tag="measured" />}
      />
      <CardBody className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-2">
          {creation ? (
            <Badge className={CREATION_LABEL[creation.status]?.tone}>{CREATION_LABEL[creation.status]?.label ?? creation.status}</Badge>
          ) : null}
          {wd ? <Badge className={WITHDRAWAL_LABEL[wd.status]?.tone}>{WITHDRAWAL_LABEL[wd.status]?.label ?? wd.status}</Badge> : null}
          {fx.same_range_as_simulation === false ? (
            <span className="inline-flex items-center gap-0.5 text-xs text-faint">
              different range
              <InfoTip label="Range difference" align="start">
                The simulation used range [{fx.simulated_position?.tick_lower}, {fx.simulated_position?.tick_upper}). Whether an
                operation reverts carries over; measured amounts apply only qualitatively.
              </InfoTip>
            </span>
          ) : null}
        </div>
        {creation?.status === "rejected" && creation.revert ? (
          <p className="break-words font-mono text-xs text-muted">
            {creation.step}: {creation.revert}
          </p>
        ) : null}

        {fx.withdrawal_blocked_under?.length ? (
          <ul className="flex flex-col gap-2">
            {fx.withdrawal_blocked_under.map((w) => (
              <li key={`${w.scenario}-${w.step}`} className="rounded-lg border border-bad/30 bg-bad/5 p-3 text-sm">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">Blocked under {humanize(w.condition)}</span>
                  <span className="font-mono text-xs text-faint">{w.step}</span>
                </div>
                {w.revert ? <p className="mt-1 break-words text-xs text-bad">{w.revert}</p> : null}
                {w.position_value_unwithdrawable_token1 ? (
                  <p className="mt-1 inline-flex flex-wrap items-center gap-1 text-xs text-muted">
                    Modelled value not withdrawable while it holds:
                    <span className="font-mono text-fg">
                      {groupDecimal(w.position_value_unwithdrawable_token1)} {t1}
                    </span>
                    <InfoTip label="How this value is derived" align="start">
                      {w.value_basis}
                    </InfoTip>
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        ) : null}

        {notTested.length ? (
          <details className="rounded-lg border border-line bg-bg/40 p-3 text-sm">
            <summary className="cursor-pointer text-muted hover:text-fg">
              Not tested: no position created · {notTested.length} removal step{notTested.length === 1 ? "" : "s"}
            </summary>
            <ul className="mt-2 flex flex-col gap-1 font-mono text-xs text-faint">
              {notTested.map((n) => (
                <li key={`${n.scenario}-${n.step}`}>
                  {n.step} · {n.revert ?? "reverted"}
                </li>
              ))}
            </ul>
          </details>
        ) : null}

        {fx.withdrawal_succeeded_under?.length ? (
          <p className="text-xs text-muted">Removal succeeded with a position under: {fx.withdrawal_succeeded_under.map(humanize).join(", ")}</p>
        ) : null}
        {fx.withdrawal_recovered_after?.length ? (
          <p className="text-xs text-muted">Removal succeeded once the condition was cleared: {fx.withdrawal_recovered_after.map(humanize).join(", ")}</p>
        ) : null}
        {wd?.unsupported_scenarios?.length ? (
          <p className="text-xs text-faint">Not run (unsupported): {wd.unsupported_scenarios.map(humanize).join(", ")}</p>
        ) : null}

        <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
          {fx.fee ? (
            <div className="rounded-lg border border-line p-3 text-sm">
              <p className="inline-flex items-center gap-0.5 text-xs uppercase tracking-wide text-faint">
                LP fee observed
                <InfoTip label="Fee source" align="start">
                  {fx.fee.basis}. Past observation, not expected future fees.
                </InfoTip>
              </p>
              <p className="mt-1 font-mono">
                {fx.fee.baseline_fee_pips ?? "—"} pips
                {fx.fee.max_fee_after_owner_change_pips != null ? ` → ${fx.fee.max_fee_after_owner_change_pips} after owner change` : ""}
              </p>
            </div>
          ) : null}
          {fx.round_trip ? (
            <div className="rounded-lg border border-line p-3 text-sm">
              <p className="inline-flex items-center gap-0.5 text-xs uppercase tracking-wide text-faint">
                Simulated round trip
                <InfoTip label="Round trip" align="start">
                  {String(fx.round_trip.description ?? "")}
                </InfoTip>
              </p>
              <p className="mt-1 font-mono text-xs">
                Δ{t0} {groupDecimal(String(fx.round_trip.net_amount0 ?? ""), 12)} · Δ{t1} {groupDecimal(String(fx.round_trip.net_amount1 ?? ""), 12)}
              </p>
            </div>
          ) : null}
          {fx.accounting ? (
            <div className="rounded-lg border border-line p-3 text-sm">
              <p className="text-xs uppercase tracking-wide text-faint">Accounting invariants</p>
              <p className="mt-1">
                <StatusBadge status={String(fx.accounting.status ?? "unknown")} />
              </p>
            </div>
          ) : null}
        </div>
      </CardBody>
    </Card>
  );
}

function Results({ r, stale }: { r: Compare; stale: boolean }) {
  const t0 = r.pool.token0.symbol ?? "token0";
  const t1 = r.pool.token1.symbol ?? "token1";
  const b = r.baseline;
  const label = (t: Tagged | undefined) =>
    t && t.value !== null && typeof t.value === "string" && /^-?\d/.test(t.value) ? `${groupDecimal(t.value, 6)} ${t1}` : undefined;
  const pk = r.position_kind;
  return (
    <div className={cn("flex flex-col gap-6 transition-opacity", stale && "opacity-70")}>
      {pk?.deposit_rejected_in_simulation ? (
        <Notice tone="warn">
          The hook rejected deposits in the applied simulation
          {pk.rejection?.fork_block ? ` (fork block ${pk.rejection.fork_block.toLocaleString()})` : ""}. This position is a model and
          could not be created as entered.
        </Notice>
      ) : null}

      <Card>
        <CardHeader
          title="Pool state"
          description={<SourceLine src={r.data_source} />}
          actions={<Badge className="font-mono text-faint">{r.calculation_version}</Badge>}
        />
        <CardBody className="grid grid-cols-2 gap-3 2xl:grid-cols-4">
          <TaggedValue label={`Price (${t1}/${t0})`} t={b.price} />
          <TaggedValue label={`Price (${t0}/${t1})`} t={b.price_inverted} />
          <TaggedValue label="Current tick" t={b.current_tick} />
          <TaggedValue label="Active liquidity" t={b.pool_active_liquidity} />
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Modelled position"
          description={`Ticks [${r.position.tick_lower}, ${r.position.tick_upper}) · L = ${groupDecimal(r.position.liquidity)}`}
          actions={
            <span className="inline-flex items-center gap-1">
              <TagBadge tag="hypothetical" />
              <InfoTip label="About the modelled position" align="end">
                {pk?.note ?? "Computed from your inputs; not an on-chain LP position."}
              </InfoTip>
            </span>
          }
        />
        <CardBody className="flex flex-col gap-4">
          <RangeBar
            tickLower={r.position.tick_lower}
            tickUpper={r.position.tick_upper}
            currentTick={r.pool.state.tick}
            lowerLabel={label(b.price_lower)}
            upperLabel={label(b.price_upper)}
            currentLabel={label(b.price) ? `price ${label(b.price)} per ${t0}` : undefined}
            currentTag={b.current_tick?.tag ?? b.price?.tag}
          />
          <div className="grid grid-cols-2 gap-3 2xl:grid-cols-4">
            <TaggedValue label="Value" t={b.value_in_token1} unit={t1} />
            <TaggedValue label={`Deposit ${t0}`} t={b.deposit_amount0} unit={t0} />
            <TaggedValue label={`Deposit ${t1}`} t={b.deposit_amount1} unit={t1} />
            <TaggedValue label="Range" t={b.range_state} />
            <TaggedValue label="Range lower" t={b.price_lower} unit={t1} />
            <TaggedValue label="Range upper" t={b.price_upper} unit={t1} />
            <TaggedValue label="Share if added (%)" t={b.share_of_active_liquidity} />
            <TaggedValue label="Fee income" t={b.fee_income} />
          </div>
          {r.notes.length ? (
            <ul className="list-disc pl-5 text-xs text-faint">
              {r.notes.map((n, i) => (
                <li key={i}>{n}</li>
              ))}
            </ul>
          ) : null}
        </CardBody>
      </Card>

      <Card>
        <CardHeader
          title="Price scenarios"
          actions={
            <span className="inline-flex items-center gap-1">
              <TagBadge tag="hypothetical" />
              <InfoTip label="Scenario assumptions" align="end">
                {(r.scenario_assumptions ?? ["Instant price moves; no fees, no hook effects."]).join(" ")}
              </InfoTip>
            </span>
          }
        />
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

      <HistoricalSimulation fx={r.simulation_effects} t0={t0} t1={t1} />
      <p className="text-xs text-faint">{r.disclaimer}</p>
    </div>
  );
}

// ---------------------------------------------------------------- form

function toBody(scanId: string, v: FormValues): CompareBody {
  return {
    scan_id: scanId,
    pool_id: v.pool_id,
    simulation_id: v.simulation_id || null,
    state_source: v.state_source,
    amount0: v.amount0 || null,
    amount1: v.amount1 || null,
    price_orientation: v.orientation,
    price_moves: v.moves ? v.moves.split(",").map((x) => Number(x.trim()) / 100) : null,
    ...(v.mode === "tick" ? { tick_lower: Number(v.lower), tick_upper: Number(v.upper) } : { price_lower: v.lower, price_upper: v.upper }),
  };
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
      state_source: "live",
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

  const values = useWatch({ control: form.control });
  const { pool_id: poolId, mode, orientation, state_source: stateSource } = values;
  const pool = pools.find((p) => p.pool_id === poolId);
  const s0 = sym(pool, 0);
  const s1 = sym(pool, 1);
  const quote = orientation === "token1_per_token0" ? `${s1} per ${s0}` : `${s0} per ${s1}`;
  const live = useLivePool(scanId, poolId || undefined);
  const liveBlock = live.data?.block_number;

  const [lastBody, setLastBody] = useState<CompareBody | null>(null);
  const run = (body: CompareBody) => {
    setLastBody(body);
    compare.mutate(body);
  };
  const onSubmit = form.handleSubmit((v) => run(toBody(scanId, v)));

  // Once a result exists: recompute when inputs change (debounced) ...
  const serialized = JSON.stringify(values);
  useEffect(() => {
    if (!lastBody) return;
    const t = setTimeout(() => {
      const parsed = schema.safeParse(getValues());
      if (!parsed.success) return;
      const body = toBody(scanId, parsed.data);
      if (JSON.stringify(body) !== JSON.stringify(lastBody)) run(body);
    }, 600);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [serialized]);
  // ... and when a newer block arrives for a live result.
  const resultBlock = compare.data?.data_source?.source === "live" ? compare.data.data_source.block_number : null;
  useEffect(() => {
    if (!lastBody || lastBody.state_source !== "live" || compare.isPending) return;
    if (liveBlock && resultBlock && liveBlock > resultBlock) compare.mutate(lastBody);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveBlock, resultBlock]);

  if (scan.isPending) return <Spinner label="Loading scan…" />;
  if (scan.isError) return <ErrorState error={scan.error} onRetry={() => scan.refetch()} />;
  if (pools.length === 0) return <EmptyState title="This scan found no pools">LP exposure needs an initialized pool that uses the hook.</EmptyState>;

  const err = form.formState.errors;
  const f = (n: string) => `${id}-${n}`;
  const desc = (n: keyof FormValues, hint = false) => [hint ? `${f(n)}-hint` : "", err[n] ? `${f(n)}-error` : ""].filter(Boolean).join(" ") || undefined;
  const behind = !!(liveBlock && resultBlock && liveBlock > resultBlock);

  return (
    <>
      <LiveStateBar scanId={scanId} pool={pool} />
      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[24rem_minmax(0,1fr)]">
        <Card className="h-fit">
          <CardHeader title="Position" />
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

              <fieldset className="flex flex-col gap-2">
                <legend className="mb-1 text-sm font-medium">Pool state</legend>
                <div className="flex flex-wrap gap-4 text-sm">
                  <label className="flex items-center gap-2">
                    <input type="radio" value="live" className="accent-[var(--color-accent)]" {...form.register("state_source")} /> Live
                  </label>
                  <label className="flex items-center gap-2">
                    <input type="radio" value="scan" className="accent-[var(--color-accent)]" {...form.register("state_source")} /> Scan snapshot
                    {scan.data?.block_number ? <span className="font-mono text-xs text-faint">#{scan.data.block_number}</span> : null}
                  </label>
                </div>
              </fieldset>

              <Field id={f("sim")} label="Apply simulation" hint="Historical fork run; shown separately.">
                <select id={f("sim")} className={inputClass} aria-describedby={`${f("sim")}-hint`} {...form.register("simulation_id")}>
                  <option value="">None</option>
                  {done.map((s) => (
                    <option key={s.id} value={s.id}>
                      {formatDate(s.created_at)} · block {s.fork_block ?? "?"} · {s.status}
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
              <p className="-mt-2 inline-flex items-center gap-0.5 text-xs text-faint">
                One token is enough in range
                <InfoTip label="How amounts are used" align="start">
                  The other token is computed from the price. With both, the scarcer one decides. Out-of-range positions hold one token.
                </InfoTip>
              </p>
              <Field id={f("moves")} label="Price moves (%)" hint="Hypothetical, vs holding." error={err.moves?.message}>
                <input id={f("moves")} className={`${inputClass} font-mono`} autoComplete="off" aria-invalid={err.moves ? true : undefined} aria-describedby={desc("moves", true)} {...form.register("moves")} />
              </Field>
              <div className="flex flex-wrap items-center gap-3">
                <Button type="submit" variant="primary" loading={compare.isPending}>
                  <Calculator aria-hidden="true" className="size-4" /> Compute exposure
                </Button>
                {stateSource === "live" ? <span className="text-xs text-faint">uses the latest block</span> : null}
              </div>
            </form>
          </CardBody>
        </Card>
        <div className="min-w-0">
          {compare.isError ? <ErrorState error={compare.error} title="Could not compute this position" /> : null}
          {compare.data ? (
            <>
              {behind ? (
                <p role="status" className="mb-3 text-xs text-faint">
                  New block {liveBlock?.toLocaleString()}; updating…
                </p>
              ) : null}
              <Results r={compare.data} stale={compare.isPending || behind} />
            </>
          ) : !compare.isError ? (
            <Card>
              <EmptyState title="Describe a position">Enter a range and amounts.</EmptyState>
            </Card>
          ) : null}
        </div>
      </div>
    </>
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

const TAG_LEGEND: [string, string][] = [
  ["live", "Read from the chain at its latest block."],
  ["historical", "From a scan snapshot at its pinned block."],
  ["measured", "Observed in a past fork simulation, at its own block."],
  ["hypothetical", "Depends on your inputs: the modelled position and price moves."],
  ["unavailable", "Not computable from available data; reason shown."],
];

function TagLegend() {
  return (
    <ul aria-label="How LP figures are labelled" className="mb-6 flex flex-wrap items-center gap-2">
      {TAG_LEGEND.map(([tag, meaning]) => (
        <li key={tag} className="inline-flex items-center gap-0.5">
          <TagBadge tag={tag} />
          <InfoTip label={`What ${tag} means`} align="start">
            {meaning}
          </InfoTip>
        </li>
      ))}
    </ul>
  );
}

export function LpView() {
  const params = useSearchParams();
  const scanId = params.get("scan");
  return (
    <>
      <PageHeader
        eyebrow="LP exposure"
        title="What is this position exposed to?"
        description="Live pool state, exact v4 math. Fee income is not forecast."
      />
      <TagLegend />
      {scanId ? <LpForm key={scanId} scanId={scanId} initialPool={params.get("pool")} initialSim={params.get("sim")} /> : <ScanPicker />}
    </>
  );
}

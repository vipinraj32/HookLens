"use client";

import { ArrowDownUp, Coins, FlaskConical, KeyRound, Lock, Radio, Scale } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";

import type { ScenarioDef } from "@/lib/api/models";
import { cn, parseUtc } from "@/lib/format";
import { OUTCOME, OUTCOMES, SCENARIO_LP, outcomeOf, type OutcomeClass } from "@/lib/outcomes";

const ICONS: Record<string, typeof Lock> = {
  withdrawal_failure: Lock,
  oracle_failure: Radio,
  fee_escalation: Coins,
  admin_upgrade: KeyRound,
  accounting_invariants: Scale,
  transaction_ordering: ArrowDownUp,
};

export function ScenarioIcon({ id, className }: { id: string; className?: string }) {
  const Icon = ICONS[id] ?? FlaskConical;
  return <Icon aria-hidden="true" className={className} />;
}

/** Outcome pill: grouped class plus the exact backend status. */
export function OutcomeBadge({ status, className }: { status: string; className?: string }) {
  const o = OUTCOME[outcomeOf(status)];
  const exact = status.replace(/_/g, " ");
  return (
    <span
      title={o.meaning}
      className={cn("inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[11px] font-medium", o.tone, className)}
    >
      <span aria-hidden="true" className={cn("size-1.5 rounded-full", o.dot, o.id === "running" && "animate-pulse")} />
      {o.label}
      {exact.toLowerCase() !== o.label.toLowerCase() ? <span className="font-normal opacity-80">· {exact}</span> : null}
    </span>
  );
}

export function OutcomeLegend({ only }: { only?: OutcomeClass[] }) {
  const items = OUTCOMES.filter((o) => o.id !== "running" && (!only || only.includes(o.id)));
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-xs sm:grid-cols-2">
      {items.map((o) => (
        <div key={o.id} className="flex gap-2">
          <dt className="flex w-24 shrink-0 items-center gap-1.5 font-medium text-fg">
            <span aria-hidden="true" className={cn("size-2 rounded-full", o.dot)} />
            {o.label}
          </dt>
          <dd className="text-muted">{o.meaning}</dd>
        </div>
      ))}
    </dl>
  );
}

/** A scenario from the backend catalogue, with its LP rationale. Optionally selectable. */
export function ScenarioCard({
  scenario,
  selected,
  onToggle,
  lastStatus,
  footer,
}: {
  scenario: ScenarioDef;
  selected?: boolean;
  onToggle?: (on: boolean) => void;
  lastStatus?: string;
  footer?: ReactNode;
}) {
  const lp = SCENARIO_LP[scenario.scenario_id];
  const selectable = onToggle !== undefined;
  const body = (
    <>
      <span className="flex items-start justify-between gap-3">
        <span
          className={cn(
            "grid size-9 shrink-0 place-items-center rounded-xl ring-1 transition-colors",
            selected ? "bg-accent text-bg ring-accent" : "bg-accent/10 text-accent ring-accent/30",
          )}
        >
          <ScenarioIcon id={scenario.scenario_id} className="size-4" />
        </span>
        {selectable ? (
          <input
            type="checkbox"
            className="mt-1 size-4 accent-[var(--color-accent)]"
            checked={!!selected}
            onChange={(e) => onToggle(e.target.checked)}
          />
        ) : null}
      </span>
      <span className="mt-3 block text-sm font-semibold text-fg">{scenario.title}</span>
      <span className="mt-1 block text-xs leading-relaxed text-muted">{scenario.description}</span>
      {lp ? (
        <span className="mt-3 block border-t border-line pt-3 text-xs leading-relaxed text-muted">
          <span className="font-medium text-fg">Why it matters to LPs. </span>
          {lp.why}
        </span>
      ) : null}
      {lastStatus || footer ? (
        <span className="mt-auto flex flex-wrap items-center gap-2 pt-3">
          {lastStatus ? (
            <>
              <span className="text-[11px] text-faint">Latest run</span>
              <OutcomeBadge status={lastStatus} />
            </>
          ) : null}
          {footer}
        </span>
      ) : null}
    </>
  );
  const cls = cn(
    "flex h-full flex-col rounded-2xl border p-4 transition-colors",
    selectable && "cursor-pointer",
    selected ? "border-accent/70 bg-accent/[0.06]" : "border-line bg-surface hover:border-line-strong",
  );
  return selectable ? <label className={cls}>{body}</label> : <div className={cls}>{body}</div>;
}

/** Elapsed time since `from` (ISO, UTC), ticking while `running`; fixed at `to` when given. */
export function Elapsed({ from, to, running }: { from: string; to?: string | null; running: boolean }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [running]);
  const end = to ? parseUtc(to).getTime() : now;
  const s = Math.max(0, Math.round((end - parseUtc(from).getTime()) / 1000));
  const text = s >= 3600 ? `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  return (
    <span className="tabular-nums" aria-label={`Elapsed ${text}`}>
      {text}
    </span>
  );
}

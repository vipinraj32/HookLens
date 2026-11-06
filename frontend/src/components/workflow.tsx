"use client";

import { Check, CircleDashed, Loader2, Minus, X } from "lucide-react";
import Link from "next/link";

import { isTerminal, useReports, useSimulations } from "@/lib/api/hooks";
import type { Report, Scan, Simulation } from "@/lib/api/models";
import { cn } from "@/lib/format";

export type StageId = "address" | "intelligence" | "pools" | "lab" | "evidence" | "lp" | "report";
export type StageState = "done" | "running" | "failed" | "unavailable" | "todo";

export type Stage = { id: StageId; label: string; state: StageState; detail: string; href: string };

const INFRA = new Set(["infra_error", "timed_out", "cancelled"]);

/**
 * Derive each workflow stage from real API data only. Nothing is marked done unless the backend
 * returned the artefact for it; stages that cannot happen (no pool, failed scan) say so.
 */
export function deriveStages(scan: Scan, sims: Simulation[] | undefined, reports: Report[] | undefined): Stage[] {
  const base = `/app/scans/${scan.id}`;
  const scanDone = isTerminal(scan.status) && scan.status !== "failed" && scan.status !== "cancelled";
  const scanFailed = scan.status === "failed" || scan.status === "cancelled";
  const hasPools = scan.pools.length > 0;
  const latest = sims?.[0];
  const latestDone = latest ? isTerminal(latest.status) : false;
  const runs = latest?.runs ?? [];
  const executed = runs.filter((r) => r.status !== "unsupported" && r.status !== "skipped" && r.status !== "queued" && r.status !== "running");
  const pool = latest?.pool_id ?? scan.pools[0]?.pool_id;
  const lpHref = `/app/lp?scan=${scan.id}${latest && latestDone ? `&sim=${latest.id}` : ""}${pool ? `&pool=${pool}` : ""}`;
  const readyReports = reports?.filter((r) => r.status === "ready" || r.status === "rendering" || r.status === "pdf_failed") ?? [];

  const stages: Stage[] = [
    { id: "address", label: "Hook address", state: "done", detail: "Resolved", href: "/app/scan" },
    {
      id: "intelligence",
      label: "Hook intelligence",
      state: scanFailed ? "failed" : scanDone ? "done" : "running",
      detail: scanFailed
        ? `Scan ${scan.status}`
        : scanDone
          ? scan.summary.finding_count !== undefined
            ? `${scan.summary.finding_count} finding${scan.summary.finding_count === 1 ? "" : "s"}`
            : "Analyzed"
          : `Scan ${scan.status}`,
      href: base,
    },
    {
      id: "pools",
      label: "Pool resolution",
      state: !scanDone ? (scanFailed ? "unavailable" : "todo") : hasPools ? "done" : "unavailable",
      detail: !scanDone ? "After the scan" : hasPools ? `${scan.pools.length} pool${scan.pools.length === 1 ? "" : "s"}` : "No initialized pool",
      href: `${base}?tab=pools`,
    },
    {
      id: "lab",
      label: "Adversarial lab",
      state: !scanDone || !hasPools ? "unavailable" : !latest ? "todo" : !latestDone ? "running" : latest.status === "failed" || INFRA.has(latest.status) ? "failed" : "done",
      detail: !scanDone || !hasPools ? "Needs a pool" : !latest ? "Not run" : !latestDone ? `Simulation ${latest.status}` : `Simulation ${latest.status.replace(/_/g, " ")}`,
      href: `${base}/lab`,
    },
    {
      id: "evidence",
      label: "Execution evidence",
      state: !latest || !latestDone ? (latest ? "running" : !scanDone || !hasPools ? "unavailable" : "todo") : executed.length ? "done" : "unavailable",
      detail: !latest ? "From lab runs" : !latestDone ? "Collecting" : executed.length ? `${executed.length} executed run${executed.length === 1 ? "" : "s"}` : "No executed runs",
      href: `${base}/lab`,
    },
    {
      id: "lp",
      label: "LP exposure",
      // LP analyses are computed on demand and not stored, so this stage is never shown as "done".
      state: !scanDone || !hasPools ? "unavailable" : "todo",
      detail: !scanDone || !hasPools ? "Needs a pool" : latest && latestDone ? "With measured effects" : "On-chain math only",
      href: lpHref,
    },
    {
      id: "report",
      label: "Report",
      state: !scanDone ? (scanFailed ? "unavailable" : "todo") : readyReports.length ? "done" : "todo",
      detail: readyReports.length ? `${readyReports.length} report${readyReports.length === 1 ? "" : "s"}` : "Not generated",
      href: readyReports[0] ? `/app/reports/${readyReports[0].id}` : `${base}?tab=reports`,
    },
  ];
  return stages;
}

const ICON: Record<StageState, typeof Check> = { done: Check, running: Loader2, failed: X, unavailable: Minus, todo: CircleDashed };
const TONE: Record<StageState, string> = {
  done: "border-ok/50 bg-ok/10 text-ok",
  running: "border-accent/60 bg-accent/10 text-accent",
  failed: "border-bad/50 bg-bad/10 text-bad",
  unavailable: "border-line text-faint",
  todo: "border-line-strong text-muted",
};
const STATE_LABEL: Record<StageState, string> = {
  done: "complete",
  running: "in progress",
  failed: "failed",
  unavailable: "unavailable",
  todo: "not started",
};

export function WorkflowStepper({ stages, current }: { stages: Stage[]; current: StageId }) {
  return (
    <nav aria-label="HookLens workflow" className="relative -mx-1 mb-6 overflow-x-auto pb-1 xl:overflow-visible">
      <ol className="flex min-w-max items-stretch gap-x-1 gap-y-2 px-1 xl:min-w-0 xl:flex-wrap">
        {stages.map((s, i) => {
          const Icon = ICON[s.state];
          const here = s.id === current;
          return (
            <li key={s.id} className="flex items-center gap-1">
              {i > 0 ? (
                <span aria-hidden="true" className={cn("h-px w-3 sm:w-4", stages[i - 1].state === "done" ? "bg-ok/50" : "bg-line")} />
              ) : null}
              <Link
                href={s.href}
                aria-current={here ? "step" : undefined}
                title={`${s.label}: ${STATE_LABEL[s.state]}. ${s.detail}`}
                className={cn(
                  "group flex items-center gap-2 rounded-xl border px-2 py-1.5 transition-colors hover:border-accent/50 hover:bg-surface-2",
                  here ? "border-accent/60 bg-accent/[0.07]" : "border-line bg-surface",
                )}
              >
                <span className={cn("grid size-5 shrink-0 place-items-center rounded-full border", TONE[s.state])}>
                  <Icon aria-hidden="true" className={cn("size-3", s.state === "running" && "animate-spin")} />
                </span>
                <span className="flex flex-col leading-tight">
                  <span className={cn("text-xs font-medium", here ? "text-fg" : "text-muted group-hover:text-fg")}>{s.label}</span>
                  <span className="text-[11px] text-faint">
                    <span className="sr-only">{STATE_LABEL[s.state]}: </span>
                    {s.detail}
                  </span>
                </span>
              </Link>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** Stepper for a scan, loading its simulations and reports. */
export function ScanWorkflow({ scan, current }: { scan: Scan; current: StageId }) {
  const ready = isTerminal(scan.status);
  const sims = useSimulations(scan.id, ready);
  const reports = useReports(scan.id);
  return <WorkflowStepper stages={deriveStages(scan, sims.data, reports.data)} current={current} />;
}

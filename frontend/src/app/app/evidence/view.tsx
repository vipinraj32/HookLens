"use client";

import { ChevronLeft, ChevronRight, Search } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { useDeferredValue, useId, useState } from "react";

import { EvidenceCard } from "@/components/evidence";
import { Button, Card, EmptyState, ErrorState, PageHeader, Spinner, inputClass } from "@/components/ui";
import { isTerminal, useEvidence, useScans } from "@/lib/api/hooks";

const KINDS = ["source_excerpt", "bytecode_fact", "permission_bits", "consistency_check", "state_variable", "metadata", "simulation_step"];
const BASES = ["source-ast", "bytecode", "metadata", "rpc-state", "simulation"];
const LIMIT = 20;

export function EvidenceView() {
  const id = useId();
  const router = useRouter();
  const params = useSearchParams();
  const scans = useScans(0, 50);
  const scanId = params.get("scan") ?? "";
  const [q, setQ] = useState(params.get("q") ?? "");
  const [kind, setKind] = useState("");
  const [basis, setBasis] = useState("");
  const [fn, setFn] = useState("");
  const [offset, setOffset] = useState(0);
  const dq = useDeferredValue(q.trim());
  const dfn = useDeferredValue(fn.trim());

  const ev = useEvidence({ scan_id: scanId, q: dq || undefined, kind: kind || undefined, basis: basis || undefined, function: dfn || undefined, offset, limit: LIMIT });
  const usable = (scans.data?.items ?? []).filter((s) => isTerminal(s.status));

  return (
    <>
      <PageHeader
        eyebrow="Evidence explorer"
        title="Evidence"
        description="Source, bytecode, on-chain state and simulation steps behind every finding."
      />
      <Card className="mb-6 p-4">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_repeat(3,minmax(0,0.8fr))]">
          <label className="flex flex-col gap-1 text-xs text-muted" htmlFor={`${id}-scan`}>
            Scan
            <select
              id={`${id}-scan`}
              className={inputClass}
              value={scanId}
              onChange={(e) => {
                setOffset(0);
                router.replace(e.target.value ? `/app/evidence?scan=${e.target.value}` : "/app/evidence");
              }}
            >
              <option value="">Select a scan…</option>
              {usable.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.hook_address.slice(0, 12)}… · chain {s.chain_id} · {s.summary.evidence_count ?? "?"} items
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted" htmlFor={`${id}-q`}>
            Search
            <span className="relative">
              <Search aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-faint" />
              <input id={`${id}-q`} type="search" value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} placeholder="title, file, ID…" className={`${inputClass} pl-9`} />
            </span>
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted" htmlFor={`${id}-kind`}>
            Kind
            <select id={`${id}-kind`} className={inputClass} value={kind} onChange={(e) => { setKind(e.target.value); setOffset(0); }}>
              <option value="">All</option>
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {k.replace(/_/g, " ")}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted" htmlFor={`${id}-basis`}>
            Basis
            <select id={`${id}-basis`} className={inputClass} value={basis} onChange={(e) => { setBasis(e.target.value); setOffset(0); }}>
              <option value="">All</option>
              {BASES.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs text-muted" htmlFor={`${id}-fn`}>
            Function
            <input id={`${id}-fn`} value={fn} onChange={(e) => { setFn(e.target.value); setOffset(0); }} placeholder="e.g. beforeSwap" className={`${inputClass} font-mono`} />
          </label>
        </div>
      </Card>

      {!scanId ? (
        <Card>
          <EmptyState title="Pick a scan">{scans.isPending ? "Loading scans…" : usable.length ? "Evidence is scoped to one scan." : "Run a scan first."}</EmptyState>
        </Card>
      ) : ev.isPending ? (
        <Spinner label="Loading evidence…" />
      ) : ev.isError ? (
        <ErrorState error={ev.error} onRetry={() => ev.refetch()} />
      ) : ev.data.items.length === 0 ? (
        <Card>
          <EmptyState title="No matching evidence">Try clearing a filter.</EmptyState>
        </Card>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex items-center justify-between text-xs text-muted">
            <span aria-live="polite">
              {offset + 1}–{Math.min(offset + LIMIT, ev.data.total)} of {ev.data.total}
              {ev.isFetching ? " · updating…" : ""}
            </span>
            <span className="flex gap-1">
              <Button size="icon" variant="ghost" aria-label="Previous page" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - LIMIT))}>
                <ChevronLeft aria-hidden="true" className="size-4" />
              </Button>
              <Button size="icon" variant="ghost" aria-label="Next page" disabled={offset + LIMIT >= ev.data.total} onClick={() => setOffset(offset + LIMIT)}>
                <ChevronRight aria-hidden="true" className="size-4" />
              </Button>
            </span>
          </div>
          {ev.data.items.map((e) => (
            <EvidenceCard key={e.evidence_id} ev={e} compact />
          ))}
        </div>
      )}
    </>
  );
}

"use client";

import { ChevronRight, FileCode2, Search } from "lucide-react";
import { useId, useMemo, useState } from "react";

import { SeverityBadge } from "@/components/ui";
import { cn } from "@/lib/format";

import { SAMPLE_CONTRACTS, SAMPLE_FINDINGS, SAMPLE_META } from "./sample-report";

const LEVELS = ["medium", "low", "informational"] as const;
const DOT: Record<string, string> = {
  critical: "bg-sev-critical",
  high: "bg-sev-high",
  medium: "bg-sev-medium",
  low: "bg-sev-low",
  informational: "bg-sev-info",
};

export function FindingExplorer() {
  const searchId = useId();
  const [levels, setLevels] = useState<Set<string>>(new Set(["medium", "low"]));
  const [contract, setContract] = useState<string>("all");
  const [query, setQuery] = useState("");

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const f of SAMPLE_FINDINGS) c[f.severity] = (c[f.severity] ?? 0) + 1;
    return c;
  }, []);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return SAMPLE_FINDINGS.filter(
      (f) =>
        levels.has(f.severity) &&
        (contract === "all" || f.contract === contract) &&
        (!q || `${f.title} ${f.rule} ${f.contract} ${f.description}`.toLowerCase().includes(q)),
    );
  }, [levels, contract, query]);

  const toggle = (lvl: string) =>
    setLevels((prev) => {
      const next = new Set(prev);
      if (next.has(lvl)) next.delete(lvl);
      else next.add(lvl);
      return next;
    });

  return (
    <div className="overflow-hidden rounded-xl border border-line bg-bg">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-surface px-4 py-3">
        <p className="font-mono text-xs text-muted">
          <span className="text-accent">$</span> {SAMPLE_META.command}
          <span className="ml-3 text-faint">
            {SAMPLE_META.contractsAnalyzed} contracts · {SAMPLE_META.findings} findings · {SAMPLE_META.tool}
          </span>
        </p>
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Filter by severity">
          {LEVELS.map((lvl) => (
            <button
              key={lvl}
              type="button"
              onClick={() => toggle(lvl)}
              aria-pressed={levels.has(lvl)}
              className="inline-flex items-center gap-1.5 rounded-full border border-line px-2.5 py-1 text-xs text-faint transition-colors hover:text-fg aria-pressed:border-fg/30 aria-pressed:bg-surface-2 aria-pressed:text-fg"
            >
              <span aria-hidden="true" className={cn("size-2 rounded-full", DOT[lvl])} />
              {lvl} <span className="tabular-nums text-faint">{counts[lvl] ?? 0}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap gap-3 border-b border-line px-4 py-3">
        <label htmlFor={searchId} className="relative min-w-48 flex-1">
          <span className="sr-only">Search findings</span>
          <Search aria-hidden="true" className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-faint" />
          <input
            id={searchId}
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search: oracle, withdrawal, fee…"
            className="h-9 w-full rounded-md border border-line bg-surface pl-8 pr-3 text-sm outline-none focus-visible:border-accent"
          />
        </label>
        <select
          aria-label="Filter by contract"
          value={contract}
          onChange={(e) => setContract(e.target.value)}
          className="h-9 rounded-md border border-line bg-surface px-2 text-sm outline-none focus-visible:border-accent"
        >
          <option value="all">All contracts</option>
          {SAMPLE_CONTRACTS.map((c) => (
            <option key={c.name} value={c.name}>
              {c.name}
            </option>
          ))}
        </select>
      </div>

      <p className="sr-only" aria-live="polite">
        {shown.length} findings shown
      </p>
      <ul className="max-h-[34rem] divide-y divide-line overflow-y-auto">
        {shown.length === 0 ? (
          <li className="px-4 py-10 text-center text-sm text-muted">No findings match these filters.</li>
        ) : (
          shown.map((f) => (
            <li key={f.id}>
              <details className="group">
                <summary className="flex cursor-pointer list-none items-start gap-3 px-4 py-3 hover:bg-surface/60 [&::-webkit-details-marker]:hidden">
                  <ChevronRight
                    aria-hidden="true"
                    className="mt-0.5 size-4 shrink-0 text-faint transition-transform group-open:rotate-90"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-2">
                      <SeverityBadge severity={f.severity} />
                      <span className="text-sm font-medium">{f.title}</span>
                    </span>
                    <span className="mt-1 block truncate font-mono text-[11.5px] text-faint">
                      {f.rule} · {f.contract}
                      {f.file ? ` · ${f.file.replace(/^contracts\//, "")}:${f.line ?? ""}` : ""}
                    </span>
                  </span>
                </summary>
                <div className="grid gap-3 px-4 pb-4 pl-11 text-sm">
                  <p className="text-muted">{f.description}</p>
                  {f.lp ? (
                    <p>
                      <span className="text-xs font-medium uppercase tracking-wide text-warn">LP impact</span>
                      <span className="mt-1 block text-muted">{f.lp}</span>
                    </p>
                  ) : null}
                  {f.remediation ? (
                    <p>
                      <span className="text-xs font-medium uppercase tracking-wide text-accent">What to check</span>
                      <span className="mt-1 block text-muted">{f.remediation}</span>
                    </p>
                  ) : null}
                  {f.excerpt ? (
                    <figure className="rounded-lg border border-line bg-surface">
                      <figcaption className="flex items-center gap-1.5 border-b border-line px-3 py-1.5 font-mono text-[11px] text-faint">
                        <FileCode2 aria-hidden="true" className="size-3.5" />
                        {f.file.replace(/^contracts\//, "")}:{f.line}
                        {f.fn ? ` · ${f.fn}` : ""}
                      </figcaption>
                      <pre className="overflow-x-auto p-3 font-mono text-[12px] leading-relaxed text-fg/85">
                        <code>{f.excerpt}</code>
                      </pre>
                    </figure>
                  ) : null}
                  <p className="font-mono text-[11px] text-faint">
                    {f.id} · basis: {f.basis}
                  </p>
                </div>
              </details>
            </li>
          ))
        )}
      </ul>
      <p className="border-t border-line px-4 py-2.5 text-xs text-faint">
        Real output from scanning this repository&apos;s deliberately flawed test fixtures. Findings are static
        indicators for review, not confirmed exploits.
      </p>
    </div>
  );
}

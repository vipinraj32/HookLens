"use client";

import { FileCode2 } from "lucide-react";

import type { Evidence } from "@/lib/api/models";

import { Badge, CodeBlock, TagBadge } from "./ui";

interface Excerpt {
  file?: string;
  line_start?: number;
  line_end?: number;
  code?: string;
  truncated?: boolean;
}

function SourceExcerpt({ ex }: { ex: Excerpt }) {
  const start = ex.line_start ?? 1;
  const lines = (ex.code ?? "").split("\n");
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-bg">
      <div className="flex items-center gap-2 border-b border-line px-3 py-1.5 text-xs text-muted">
        <FileCode2 aria-hidden="true" className="size-3.5" />
        <span className="truncate font-mono">
          {ex.file}:{start}
          {ex.line_end && ex.line_end !== start ? `-${ex.line_end}` : ""}
        </span>
        {ex.truncated ? <span className="text-warn">(truncated)</span> : null}
      </div>
      <pre className="overflow-x-auto py-2 font-mono text-[12.5px] leading-relaxed">
        {lines.map((l, i) => (
          <div key={i} className="flex">
            <span aria-hidden="true" className="w-12 shrink-0 select-none pr-3 text-right text-faint">
              {start + i}
            </span>
            <code className="whitespace-pre pr-4 text-fg/90">{l}</code>
          </div>
        ))}
      </pre>
    </div>
  );
}

export function EvidenceCard({ ev, compact = false }: { ev: Evidence; compact?: boolean }) {
  const excerpt = (ev.data as { excerpt?: Excerpt }).excerpt;
  const rest = Object.fromEntries(Object.entries(ev.data).filter(([k]) => k !== "excerpt"));
  return (
    <article id={ev.evidence_id} className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-4">
      <header className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs text-accent">{ev.evidence_id}</span>
        <Badge className="text-muted">{ev.kind.replace(/_/g, " ")}</Badge>
        <TagBadge tag={ev.basis} />
        {ev.function_name ? <Badge className="font-mono text-muted">{ev.function_name}</Badge> : null}
        {ev.simulation_id ? <Badge className="text-ok">simulation</Badge> : null}
      </header>
      <h3 className="text-sm font-medium text-fg">{ev.title}</h3>
      {excerpt?.code ? <SourceExcerpt ex={excerpt} /> : null}
      {Object.keys(rest).length > 0 ? (
        compact ? (
          <details className="text-xs">
            <summary className="cursor-pointer text-muted hover:text-fg">Raw data</summary>
            <CodeBlock className="mt-2 max-h-80 overflow-auto" code={JSON.stringify(rest, null, 2)} />
          </details>
        ) : (
          <CodeBlock className="max-h-96 overflow-auto" code={JSON.stringify(rest, null, 2)} />
        )
      ) : null}
    </article>
  );
}

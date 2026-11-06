"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import Link from "next/link";
import { useState, type ReactNode } from "react";

import { Button, Card, CardHeader, EmptyState, ErrorState, SeverityBadge, Skeleton, StatusBadge } from "@/components/ui";
import { useChains, useScans, type ScanFilter } from "@/lib/api/hooks";
import { SEVERITIES, type ScanSummary } from "@/lib/api/models";
import { formatDate } from "@/lib/format";

/** Paginated list of this workspace's scans, read from GET /scans. */
export function ScanTable({
  title,
  description,
  filter,
  limit = 20,
  href,
  action,
  empty,
}: {
  title: string;
  description?: string;
  filter?: ScanFilter;
  limit?: number;
  href: (s: ScanSummary) => string;
  action?: (s: ScanSummary) => ReactNode;
  empty: ReactNode;
}) {
  const [offset, setOffset] = useState(0);
  const scans = useScans(offset, limit, filter);
  const chains = useChains();
  const chainName = (id: number) => chains.data?.find((c) => c.chain_id === id)?.name ?? `Chain ${id}`;

  return (
    <Card>
      <CardHeader
        title={title}
        description={scans.data ? `${scans.data.total} total${description ? ` · ${description}` : ""}` : description}
        actions={
          scans.data && scans.data.total > limit ? (
            <div className="flex items-center gap-1">
              <Button size="icon" variant="ghost" aria-label="Previous page" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>
                <ChevronLeft aria-hidden="true" className="size-4" />
              </Button>
              <span className="text-xs text-muted">
                {offset + 1}–{Math.min(offset + limit, scans.data.total)}
              </span>
              <Button size="icon" variant="ghost" aria-label="Next page" disabled={offset + limit >= scans.data.total} onClick={() => setOffset(offset + limit)}>
                <ChevronRight aria-hidden="true" className="size-4" />
              </Button>
            </div>
          ) : null
        }
      />
      {scans.isPending ? (
        <div className="space-y-2 p-5">
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
          <Skeleton className="h-10" />
        </div>
      ) : scans.isError ? (
        <div className="p-5">
          <ErrorState error={scans.error} onRetry={() => scans.refetch()} />
        </div>
      ) : scans.data.items.length === 0 ? (
        empty
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm">
            <thead className="text-left text-xs uppercase tracking-wide text-faint">
              <tr className="border-b border-line">
                <th scope="col" className="px-5 py-2.5 font-medium">Hook</th>
                <th scope="col" className="px-3 py-2.5 font-medium">Chain</th>
                <th scope="col" className="px-3 py-2.5 font-medium">Status</th>
                <th scope="col" className="px-3 py-2.5 font-medium">Findings</th>
                <th scope="col" className="px-3 py-2.5 font-medium">Created</th>
                {action ? (
                  <th scope="col" className="px-5 py-2.5 font-medium">
                    <span className="sr-only">Action</span>
                  </th>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {scans.data.items.map((s) => {
                const by = s.summary.by_severity ?? {};
                return (
                  <tr key={s.id} className="border-b border-line/60 last:border-0 hover:bg-surface-2/50">
                    <td className="px-5 py-3">
                      <Link href={href(s)} className="font-mono text-[13px] text-accent hover:underline">
                        {s.hook_address}
                      </Link>
                      {s.block_number !== null && s.block_number !== undefined ? (
                        <span className="ml-2 text-xs text-faint">@ {s.block_number}</span>
                      ) : null}
                    </td>
                    <td className="px-3 py-3 text-muted">{chainName(s.chain_id)}</td>
                    <td className="px-3 py-3">
                      <StatusBadge status={s.status} />
                    </td>
                    <td className="px-3 py-3">
                      {s.summary.finding_count === undefined ? (
                        <span className="text-faint">—</span>
                      ) : (
                        <span className="flex flex-wrap gap-1">
                          {SEVERITIES.filter((k) => (by[k] ?? 0) > 0).map((k) => (
                            <span key={k} className="inline-flex items-center gap-1">
                              <SeverityBadge severity={k} />
                              <span className="text-xs text-muted">{by[k]}</span>
                            </span>
                          ))}
                          {s.summary.finding_count === 0 ? <span className="text-xs text-muted">none reported</span> : null}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-3 text-muted">{formatDate(s.created_at)}</td>
                    {action ? <td className="px-5 py-3 text-right">{action(s)}</td> : null}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

export function NoScans({ children }: { children?: ReactNode }) {
  return (
    <EmptyState
      title="No scans yet"
      action={
        <Button variant="primary" asChild>
          <Link href="/app/scan">Analyze a hook</Link>
        </Button>
      }
    >
      {children ?? "Enter a Uniswap v4 hook address to decode its permissions, run the analyzers and discover its pools."}
    </EmptyState>
  );
}

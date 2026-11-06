"use client";

import { ChevronLeft, ChevronRight, ScanSearch } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Mono, PageHeader, SeverityBadge, Skeleton, StatusBadge } from "@/components/ui";
import { useChains, useScans } from "@/lib/api/hooks";
import { SEVERITIES } from "@/lib/api/models";
import { formatDate } from "@/lib/format";

const LIMIT = 20;

export default function Dashboard() {
  const [offset, setOffset] = useState(0);
  const scans = useScans(offset, LIMIT);
  const chains = useChains();
  const chainName = (id: number) => chains.data?.find((c) => c.chain_id === id)?.name ?? `Chain ${id}`;

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Scans in this browser's anonymous workspace. Nothing here is shared unless you export a report."
        actions={
          <Button variant="primary" asChild>
            <Link href="/app/scan">
              <ScanSearch aria-hidden="true" className="size-4" /> New scan
            </Link>
          </Button>
        }
      />

      {chains.data ? (
        <div className="mb-6 grid gap-3 sm:grid-cols-2">
          {chains.data.map((c) => (
            <Card key={c.chain_id} className="px-5 py-4">
              <div className="flex items-center justify-between gap-2">
                <p className="text-sm font-medium">{c.name}</p>
                <Badge className={c.rpc_configured ? "border-ok/40 text-ok" : "border-warn/40 text-warn"}>
                  {c.rpc_configured ? "RPC configured" : "RPC not configured"}
                </Badge>
              </div>
              <p className="mt-1 text-xs text-faint">
                chain {c.chain_id} · PoolManager <Mono value={c.pool_manager} short copy={false} />
              </p>
              {c.notes?.length ? <p className="mt-2 text-xs text-muted">{c.notes.join(" ")}</p> : null}
            </Card>
          ))}
        </div>
      ) : null}

      <Card>
        <CardHeader
          title="Recent scans"
          description={scans.data ? `${scans.data.total} total` : undefined}
          actions={
            scans.data && scans.data.total > LIMIT ? (
              <div className="flex items-center gap-1">
                <Button size="icon" variant="ghost" aria-label="Previous page" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - LIMIT))}>
                  <ChevronLeft aria-hidden="true" className="size-4" />
                </Button>
                <span className="text-xs text-muted">
                  {offset + 1}–{Math.min(offset + LIMIT, scans.data.total)}
                </span>
                <Button size="icon" variant="ghost" aria-label="Next page" disabled={offset + LIMIT >= scans.data.total} onClick={() => setOffset(offset + LIMIT)}>
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
          <EmptyState
            title="No scans yet"
            action={
              <Button variant="primary" asChild>
                <Link href="/app/scan">Scan a hook</Link>
              </Button>
            }
          >
            Enter a Uniswap v4 hook address to decode its permissions, run the analyzers and discover its pools.
          </EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-faint">
                <tr className="border-b border-line">
                  <th scope="col" className="px-5 py-2.5 font-medium">Hook</th>
                  <th scope="col" className="px-3 py-2.5 font-medium">Chain</th>
                  <th scope="col" className="px-3 py-2.5 font-medium">Status</th>
                  <th scope="col" className="px-3 py-2.5 font-medium">Findings</th>
                  <th scope="col" className="px-5 py-2.5 font-medium">Created</th>
                </tr>
              </thead>
              <tbody>
                {scans.data.items.map((s) => {
                  const by = s.summary.by_severity ?? {};
                  return (
                    <tr key={s.id} className="border-b border-line/60 last:border-0 hover:bg-surface-2/50">
                      <td className="px-5 py-3">
                        <Link href={`/app/scans/${s.id}`} className="font-mono text-[13px] text-accent hover:underline">
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
                            {s.summary.finding_count === 0 ? <span className="text-xs text-muted">none</span> : null}
                          </span>
                        )}
                      </td>
                      <td className="px-5 py-3 text-muted">{formatDate(s.created_at)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

"use client";

import { ChevronLeft, ChevronRight, FileText } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { Badge, Button, Card, CardHeader, CopyButton, EmptyState, ErrorState, Mono, PageHeader, Skeleton, StatusBadge } from "@/components/ui";
import { apiUrl } from "@/lib/api/client";
import { useChains, useWorkspaceReports } from "@/lib/api/hooks";
import { formatDate } from "@/lib/format";
import { useNetwork } from "@/lib/network";

const LIMIT = 20;

export default function ReportsIndex() {
  const [network] = useNetwork();
  const [offset, setOffset] = useState(0);
  const reports = useWorkspaceReports(offset, LIMIT, network);
  const chains = useChains();
  const chainName = (id: number) => chains.data?.find((c) => c.chain_id === id)?.name ?? `Chain ${id}`;

  return (
    <>
      <PageHeader
        eyebrow="Reports"
        title="Generated reports"
        description="Hashed JSON and PDF. Generate from a scan."
      />
      <Card>
        <CardHeader
          title="All reports"
          description={reports.data ? `${reports.data.total} total` : undefined}
          actions={
            reports.data && reports.data.total > LIMIT ? (
              <div className="flex items-center gap-1">
                <Button size="icon" variant="ghost" aria-label="Previous page" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - LIMIT))}>
                  <ChevronLeft aria-hidden="true" className="size-4" />
                </Button>
                <span className="text-xs text-muted">
                  {offset + 1}–{Math.min(offset + LIMIT, reports.data.total)}
                </span>
                <Button size="icon" variant="ghost" aria-label="Next page" disabled={offset + LIMIT >= reports.data.total} onClick={() => setOffset(offset + LIMIT)}>
                  <ChevronRight aria-hidden="true" className="size-4" />
                </Button>
              </div>
            ) : null
          }
        />
        {reports.isPending ? (
          <div className="space-y-2 p-5">
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
          </div>
        ) : reports.isError ? (
          <div className="p-5">
            <ErrorState error={reports.error} onRetry={() => reports.refetch()} />
          </div>
        ) : reports.data.items.length === 0 ? (
          <EmptyState
            title="No reports yet"
            icon={<FileText aria-hidden="true" className="size-8" />}
            action={
              <Button variant="primary" asChild>
                <Link href="/app/scans">Choose a scan</Link>
              </Button>
            }
          >
            Open a scan in Hook Intelligence and use its Reports tab to generate a JSON and PDF report.
          </EmptyState>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[820px] text-sm">
              <thead className="text-left text-xs uppercase tracking-wide text-faint">
                <tr className="border-b border-line">
                  <th scope="col" className="px-5 py-2.5 font-medium">Report</th>
                  <th scope="col" className="px-3 py-2.5 font-medium">Hook</th>
                  <th scope="col" className="px-3 py-2.5 font-medium">Chain</th>
                  <th scope="col" className="px-3 py-2.5 font-medium">Status</th>
                  <th scope="col" className="px-3 py-2.5 font-medium">Content hash</th>
                  <th scope="col" className="px-5 py-2.5 font-medium">Export</th>
                </tr>
              </thead>
              <tbody>
                {reports.data.items.map((r) => (
                  <tr key={r.id} className="border-b border-line/60 last:border-0 hover:bg-surface-2/50">
                    <td className="px-5 py-3">
                      <Link href={`/app/reports/${r.id}`} className="text-accent hover:underline">
                        {formatDate(r.created_at)}
                      </Link>
                      {r.simulation_id ? <Badge className="ml-2 text-ok">with simulation</Badge> : null}
                    </td>
                    <td className="px-3 py-3">
                      <Mono value={r.hook_address} short />
                    </td>
                    <td className="px-3 py-3 text-muted">{chainName(r.chain_id)}</td>
                    <td className="px-3 py-3">
                      <StatusBadge status={r.status} />
                    </td>
                    <td className="px-3 py-3">
                      <span className="inline-flex items-center gap-1 font-mono text-xs text-faint">
                        {r.content_hash.slice(0, 14)}…
                        <CopyButton value={r.content_hash} label="Copy hash" />
                      </span>
                    </td>
                    <td className="px-5 py-3">
                      <span className="flex gap-2">
                        <Button size="sm" asChild>
                          <Link href={`/app/reports/${r.id}`}>Open</Link>
                        </Button>
                        {r.pdf_available ? (
                          <Button size="sm" asChild>
                            <a href={apiUrl(`/reports/${r.id}/pdf`)} download>
                              PDF
                            </a>
                          </Button>
                        ) : null}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

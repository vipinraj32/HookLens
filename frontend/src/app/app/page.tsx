"use client";

import { ArrowRight, FileText, FlaskConical, Gauge, ScanSearch, ShieldAlert } from "lucide-react";
import Link from "next/link";
import type { ComponentType } from "react";

import { NoScans, ScanTable } from "@/components/scan-table";
import { Badge, Button, Card, Mono, PageHeader, Skeleton } from "@/components/ui";
import { isTerminal, useChains, useScans } from "@/lib/api/hooks";
import type { ScanSummary } from "@/lib/api/models";
import { cn, shortHex } from "@/lib/format";
import { useNetwork } from "@/lib/network";

type Tile = { icon: ComponentType<{ className?: string }>; title: string; body: string; href: string; primary?: boolean };

/** Next steps derived only from the user's latest real scan. */
function nextActions(latest: ScanSummary | undefined): Tile[] {
  const scan: Tile = {
    icon: ScanSearch,
    title: latest ? "Analyze another hook" : "Analyze your first hook",
    body: "Paste a deployed v4 hook address. HookLens pins a block and decodes its permissions.",
    href: "/app/scan",
    primary: !latest,
  };
  if (!latest) return [scan];
  const hook = shortHex(latest.hook_address);
  const done = isTerminal(latest.status) && latest.status !== "failed" && latest.status !== "cancelled";
  if (!done) {
    return [
      {
        icon: ShieldAlert,
        title: `Follow the scan of ${hook}`,
        body: `Status: ${latest.status}. Findings appear as soon as the analyzers finish.`,
        href: `/app/scans/${latest.id}`,
        primary: true,
      },
      scan,
    ];
  }
  const n = latest.summary.finding_count;
  return [
    {
      icon: ShieldAlert,
      title: `Review ${hook}`,
      body: n === undefined ? "Open the permission matrix and findings." : `${n} finding${n === 1 ? "" : "s"} to review, each with evidence.`,
      href: `/app/scans/${latest.id}`,
      primary: true,
    },
    {
      icon: FlaskConical,
      title: "Run the Adversarial Lab",
      body: "Execute fork scenarios against this hook's pool and inspect each step.",
      href: `/app/scans/${latest.id}/lab`,
    },
    {
      icon: Gauge,
      title: "Model an LP position",
      body: "Exact v4 math for a range in one of its pools.",
      href: `/app/lp?scan=${latest.id}`,
    },
    scan,
  ];
}

export default function Overview() {
  const [network] = useNetwork();
  const latest = useScans(0, 1, { chain_id: network });
  const chains = useChains();
  const visibleChains = chains.data?.filter((c) => network === null || c.chain_id === network);
  const tiles = latest.data ? nextActions(latest.data.items[0]) : null;

  return (
    <>
      <PageHeader
        title="Overview"
        description="Scans in this browser's anonymous workspace. Nothing here is shared unless you export a report."
        actions={
          <Button variant="primary" asChild>
            <Link href="/app/scan">
              <ScanSearch aria-hidden="true" className="size-4" /> Analyze a hook
            </Link>
          </Button>
        }
      />

      <section aria-label="Next steps" className="mb-6">
        {tiles ? (
          <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {tiles.map(({ icon: Icon, title, body, href, primary }) => (
              <li key={title}>
                <Link
                  href={href}
                  className={cn(
                    "group flex h-full flex-col gap-2 rounded-2xl border p-4 transition-colors",
                    primary ? "border-accent/50 bg-accent/10 hover:bg-accent/15" : "border-line bg-surface hover:border-violet/50 hover:bg-surface-2",
                  )}
                >
                  <span className="flex items-center justify-between">
                    <Icon className={cn("size-5", primary ? "text-accent" : "text-violet")} />
                    <ArrowRight aria-hidden="true" className="size-4 text-faint transition-transform group-hover:translate-x-0.5" />
                  </span>
                  <span className="text-sm font-semibold">{title}</span>
                  <span className="text-xs text-muted">{body}</span>
                </Link>
              </li>
            ))}
            <li>
              <Link
                href="/app/reports"
                className="group flex h-full flex-col gap-2 rounded-2xl border border-line bg-surface p-4 transition-colors hover:border-violet/50 hover:bg-surface-2"
              >
                <span className="flex items-center justify-between">
                  <FileText className="size-5 text-violet" />
                  <ArrowRight aria-hidden="true" className="size-4 text-faint" />
                </span>
                <span className="text-sm font-semibold">Reports</span>
                <span className="text-xs text-muted">JSON and PDF reports you generated.</span>
              </Link>
            </li>
          </ul>
        ) : latest.isPending ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Skeleton className="h-28" />
            <Skeleton className="h-28" />
          </div>
        ) : null}
      </section>

      {visibleChains?.length ? (
        <div className="mb-6 grid gap-3 sm:grid-cols-2">
          {visibleChains.map((c) => (
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

      <ScanTable
        title="Recent scans"
        description={network === null ? "all networks" : undefined}
        filter={{ chain_id: network }}
        href={(s) => `/app/scans/${s.id}`}
        empty={<NoScans />}
      />
    </>
  );
}

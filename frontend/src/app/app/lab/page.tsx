"use client";

import { FlaskConical } from "lucide-react";
import Link from "next/link";

import { NoScans, ScanTable } from "@/components/scan-table";
import { Button, Notice, PageHeader } from "@/components/ui";
import { isTerminal, useScenarios, useWorkerHealth } from "@/lib/api/hooks";
import { useNetwork } from "@/lib/network";

export default function LabIndex() {
  const [network] = useNetwork();
  const health = useWorkerHealth();
  const scenarios = useScenarios();
  return (
    <>
      <PageHeader
        eyebrow="Adversarial Lab"
        title="Execute scenarios on a fork"
        description="The lab runs Foundry tests against a scanned hook's real pool at a pinned block. Choose a completed scan to open its lab."
      />
      {health.data && !health.data.forge.available ? (
        <Notice tone="warn" className="mb-4">
          Foundry is not available on this server, so simulations cannot run. Install it with foundryup and restart
          the backend.
        </Notice>
      ) : null}
      {scenarios.data ? (
        <ul aria-label="Scenario categories" className="mb-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {scenarios.data.map((s) => (
            <li key={s.scenario_id} className="rounded-2xl border border-line bg-surface p-4">
              <p className="flex items-center gap-2 text-sm font-semibold">
                <FlaskConical aria-hidden="true" className="size-4 text-accent" />
                {s.title}
              </p>
              <p className="mt-1.5 text-xs text-muted">{s.description}</p>
            </li>
          ))}
        </ul>
      ) : null}
      <ScanTable
        title="Scans available to simulate"
        filter={{ chain_id: network }}
        href={(s) => `/app/scans/${s.id}/lab`}
        action={(s) =>
          isTerminal(s.status) && s.status !== "failed" && s.status !== "cancelled" ? (
            <Button size="sm" asChild>
              <Link href={`/app/scans/${s.id}/lab`}>Open lab</Link>
            </Button>
          ) : (
            <span className="text-xs text-faint">scan {s.status}</span>
          )
        }
        empty={<NoScans>Scan a hook first. The lab needs a completed scan with at least one discovered pool.</NoScans>}
      />
    </>
  );
}

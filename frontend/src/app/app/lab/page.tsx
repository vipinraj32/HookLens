"use client";

import { Info } from "lucide-react";
import Link from "next/link";

import { OutcomeLegend, ScenarioCard } from "@/components/scenarios";
import { NoScans, ScanTable } from "@/components/scan-table";
import { Button, Card, CardBody, CardHeader, ErrorState, Notice, PageHeader, Skeleton } from "@/components/ui";
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
        title="Execute adversarial scenarios on a fork"
        description="Foundry scenarios on a fork of the hook's real pool. Start from a completed scan."
      />
      {health.data && !health.data.forge.available ? (
        <Notice tone="warn" className="mb-4">
          Foundry unavailable. Install with foundryup and restart the backend.
        </Notice>
      ) : null}

      <section aria-labelledby="catalogue-h" className="mb-8">
        <h2 id="catalogue-h" className="mb-3 text-sm font-semibold">
          Scenario catalogue
        </h2>
        {scenarios.isPending ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-44" />
            ))}
          </div>
        ) : scenarios.isError ? (
          <ErrorState error={scenarios.error} onRetry={() => scenarios.refetch()} />
        ) : (
          <ul aria-label="Scenario categories" className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {scenarios.data.map((s) => (
              <li key={s.scenario_id}>
                <ScenarioCard scenario={s} />
              </li>
            ))}
          </ul>
        )}
      </section>

      <Card className="mb-8">
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              <Info aria-hidden="true" className="size-4 text-muted" /> Reading results
            </span>
          }
          description="Forge outcomes at one fork block."
        />
        <CardBody>
          <OutcomeLegend />
        </CardBody>
      </Card>

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

"use client";

import { NoScans, ScanTable } from "@/components/scan-table";
import { PageHeader } from "@/components/ui";
import { useNetwork } from "@/lib/network";

export default function HookIntelligenceIndex() {
  const [network] = useNetwork();
  return (
    <>
      <PageHeader
        eyebrow="Hook Intelligence"
        title="Analyzed hooks"
        description="Open a scan to see its permission matrix, findings with evidence, proxy and dependency details, and discovered pools."
      />
      <ScanTable title="Scans" filter={{ chain_id: network }} href={(s) => `/app/scans/${s.id}`} empty={<NoScans />} />
    </>
  );
}

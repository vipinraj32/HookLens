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
        description="Permissions, findings and pools per hook."
      />
      <ScanTable title="Scans" filter={{ chain_id: network }} href={(s) => `/app/scans/${s.id}`} empty={<NoScans />} />
    </>
  );
}

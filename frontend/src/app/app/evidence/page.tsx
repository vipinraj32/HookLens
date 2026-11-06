import { Suspense } from "react";

import { Spinner } from "@/components/ui";

import { EvidenceView } from "./view";

export default function EvidencePage() {
  return (
    <Suspense fallback={<Spinner label="Loading…" />}>
      <EvidenceView />
    </Suspense>
  );
}

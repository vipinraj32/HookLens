import { Suspense } from "react";

import { Spinner } from "@/components/ui";

import { ReportView } from "./view";

export default function ReportPage() {
  return (
    <Suspense fallback={<Spinner label="Loading report…" />}>
      <ReportView />
    </Suspense>
  );
}

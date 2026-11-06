import { Suspense } from "react";

import { Spinner } from "@/components/ui";

import { ScanView } from "./view";

export default function ScanPage() {
  return (
    <Suspense fallback={<Spinner label="Loading scan…" />}>
      <ScanView />
    </Suspense>
  );
}

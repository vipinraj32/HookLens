import { Suspense } from "react";

import { Spinner } from "@/components/ui";

import { LabView } from "./view";

export default function LabPage() {
  return (
    <Suspense fallback={<Spinner label="Loading lab…" />}>
      <LabView />
    </Suspense>
  );
}

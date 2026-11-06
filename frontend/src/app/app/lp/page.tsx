import { Suspense } from "react";

import { Spinner } from "@/components/ui";

import { LpView } from "./view";

export default function LpPage() {
  return (
    <Suspense fallback={<Spinner label="Loading…" />}>
      <LpView />
    </Suspense>
  );
}

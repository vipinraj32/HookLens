"use client";

import { ErrorState } from "@/components/ui";

export default function AppError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return (
    <div className="py-10">
      <ErrorState title="This page failed to render" error={error} onRetry={reset} />
    </div>
  );
}

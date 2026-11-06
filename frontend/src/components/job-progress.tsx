"use client";

import { CircleStop } from "lucide-react";

import { useCancelJob } from "@/lib/api/hooks";
import type { JobStream } from "@/lib/api/jobs";
import { cn, parseUtc } from "@/lib/format";

import { Button, ErrorState, ProgressBar, StatusBadge } from "./ui";

export function JobProgress({ jobId, stream, title }: { jobId: string; stream: JobStream; title: string }) {
  const cancel = useCancelJob();
  const events = stream.events.slice(-40);
  // Only stages the backend actually reported, in the order they first appeared.
  const stages = [...new Set(stream.events.map((e) => e.stage))];
  const currentStage = stream.events.at(-1)?.stage;
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium">{title}</span>
          <StatusBadge status={stream.done ? stream.status : stream.status === "queued" ? "queued" : "running"} />
          <span className="text-xs text-faint">
            {stream.transport === "polling" ? "live updates via polling" : "live updates via SSE"}
          </span>
        </div>
        {!stream.done ? (
          <Button
            size="sm"
            variant="danger"
            loading={cancel.isPending}
            disabled={cancel.isSuccess}
            onClick={() => cancel.mutate(jobId)}
          >
            <CircleStop aria-hidden="true" className="size-3.5" />
            {cancel.isSuccess ? "Cancelling…" : "Cancel"}
          </Button>
        ) : null}
      </div>
      <ProgressBar value={stream.progress} label={`${title} progress`} />
      {stages.length ? (
        <ol aria-label={`${title} stages reported`} className="flex flex-wrap gap-1.5">
          {stages.map((st) => {
            const active = st === currentStage && !stream.done;
            return (
              <li
                key={st}
                aria-current={active ? "step" : undefined}
                className={cn(
                  "rounded-full border px-2.5 py-0.5 font-mono text-[11px]",
                  active ? "border-line-strong bg-surface-2 text-fg" : "border-line text-muted",
                )}
              >
                {st}
              </li>
            );
          })}
        </ol>
      ) : null}
      {cancel.isError ? <ErrorState error={cancel.error} title="Cancel failed" /> : null}
      <ol aria-live="polite" className="max-h-72 overflow-y-auto rounded-lg border border-line bg-bg p-3 font-mono text-xs">
        {events.length === 0 ? <li className="text-faint">Waiting for the worker…</li> : null}
        {events.map((e, i) => (
          <li key={`${e.ts}-${i}`} className="flex gap-3 py-0.5">
            <span className="shrink-0 text-faint">{parseUtc(e.ts).toLocaleTimeString()}</span>
            <span className="w-24 shrink-0 truncate text-muted">{e.stage}</span>
            <span className={cn("min-w-0 break-words", e.level === "warning" ? "text-warn" : e.level === "error" ? "text-bad" : "text-fg/90")}>
              {e.message}
            </span>
          </li>
        ))}
      </ol>
      {stream.done && stream.error ? (
        <ErrorState
          title={`Job ${stream.status.replace(/_/g, " ")}`}
          error={new Error(String((stream.error as { message?: string }).message ?? JSON.stringify(stream.error)))}
        />
      ) : null}
    </div>
  );
}

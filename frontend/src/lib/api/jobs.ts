"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api, apiUrl } from "./client";
import { isTerminal, keys } from "./hooks";
import * as M from "./models";

export interface JobStream {
  events: M.JobEvent[];
  status: string;
  progress: number;
  stage: string;
  error: Record<string, unknown> | null;
  /** "sse" while streaming, "polling" after falling back, "idle" without a job. */
  transport: "sse" | "polling" | "idle";
  done: boolean;
}

const EMPTY: JobStream = {
  events: [],
  status: "queued",
  progress: 0,
  stage: "queued",
  error: null,
  transport: "idle",
  done: false,
};

/**
 * Live job progress. Streams Server-Sent Events from /v1/jobs/{id}/events and falls back
 * to polling /v1/jobs/{id} if the stream cannot be established (proxy buffering, network
 * policy, or a closed connection). The DB job row is the source of truth either way.
 */
export function useJobStream(jobId: string | null | undefined, onDone?: (status: string) => void): JobStream {
  // State is tagged with the job it belongs to, so switching jobs needs no reset effect.
  const [state, setState] = useState<JobStream & { jobId: string | null }>({ ...EMPTY, jobId: null });
  const [fallbackFor, setFallbackFor] = useState<string | null>(null);
  const onDoneRef = useRef(onDone);
  useEffect(() => {
    onDoneRef.current = onDone;
  });
  const noEventSource = typeof window !== "undefined" && typeof EventSource === "undefined";
  const fallback = !!jobId && (noEventSource || fallbackFor === jobId);

  useEffect(() => {
    if (!jobId || typeof EventSource === "undefined") return;
    const es = new EventSource(apiUrl(`/jobs/${jobId}/events`), { withCredentials: true });
    let failures = 0;
    let finished = false;
    const update = (fn: (s: JobStream) => JobStream) =>
      setState((prev) => ({ ...fn(prev.jobId === jobId ? prev : { ...EMPTY, transport: "sse" }), jobId }));

    es.addEventListener("progress", (ev) => {
      failures = 0;
      try {
        const raw = JSON.parse((ev as MessageEvent<string>).data) as { status?: string };
        const data = M.JobEvent.parse(raw);
        update((s) => ({
          ...s,
          transport: "sse",
          events: [...s.events, data],
          progress: Math.max(s.progress, data.progress),
          stage: data.stage,
          status: raw.status ?? s.status,
        }));
      } catch {
        /* ignore malformed event */
      }
    });

    es.addEventListener("end", (ev) => {
      finished = true;
      es.close();
      let payload: { status?: string; progress?: number; stage?: string; error?: Record<string, unknown> | null } = {};
      try {
        payload = JSON.parse((ev as MessageEvent<string>).data);
      } catch {
        /* keep defaults */
      }
      const status = payload.status ?? "succeeded";
      update((s) => ({
        ...s,
        transport: "sse",
        status,
        progress: payload.progress ?? s.progress,
        stage: payload.stage ?? s.stage,
        error: payload.error ?? null,
        done: true,
      }));
      onDoneRef.current?.(status);
    });

    es.onerror = () => {
      if (finished) return;
      failures += 1;
      // CLOSED means the browser gave up (e.g. non-200); repeated errors mean a flaky proxy.
      if (es.readyState === EventSource.CLOSED || failures >= 3) {
        es.close();
        setFallbackFor(jobId);
      }
    };
    return () => es.close();
  }, [jobId]);

  const poll = useQuery({
    queryKey: keys.job(jobId ?? ""),
    queryFn: ({ signal }) => api.get(`/jobs/${jobId}`, M.Job, { signal }),
    enabled: fallback,
    refetchInterval: (q) => (q.state.data && isTerminal(q.state.data.status) ? false : 2000),
  });

  const polled = poll.data;
  const notified = useRef<string | null>(null);
  useEffect(() => {
    if (fallback && polled && isTerminal(polled.status) && notified.current !== polled.id) {
      notified.current = polled.id;
      onDoneRef.current?.(polled.status);
    }
  }, [fallback, polled]);

  if (!jobId) return EMPTY;
  if (fallback && polled) {
    return {
      events: polled.events,
      status: polled.status,
      progress: polled.progress,
      stage: polled.stage,
      error: polled.error ?? null,
      transport: "polling",
      done: isTerminal(polled.status),
    };
  }
  const current: JobStream = state.jobId === jobId ? state : { ...EMPTY, transport: "sse" };
  return fallback ? { ...current, transport: "polling" } : current;
}

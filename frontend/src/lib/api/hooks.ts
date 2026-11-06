"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { z } from "zod";

import { api } from "./client";
import * as M from "./models";
import type { components } from "./schema";

type Schemas = components["schemas"];
export type ScanCreateBody = Schemas["ScanCreate"];
export type SimulationCreateBody = Schemas["SimulationCreate"];
export type CompareBody = Schemas["CompareRequest"];
export type ReportCreateBody = Schemas["ReportCreate"];

const TERMINAL = new Set(["completed", "partial", "failed", "cancelled", "timed_out", "succeeded", "ready", "rejected", "unavailable"]);
export const isTerminal = (status: string | undefined) => !!status && TERMINAL.has(status);

export const keys = {
  health: ["health"] as const,
  chains: ["chains"] as const,
  scans: (offset: number, filter?: ScanFilter) => ["scans", offset, filter ?? {}] as const,
  scan: (id: string) => ["scan", id] as const,
  findings: (id: string) => ["findings", id] as const,
  scenarios: ["scenarios"] as const,
  sims: (scanId: string) => ["sims", scanId] as const,
  sim: (id: string) => ["sim", id] as const,
  run: (simId: string, runId: string) => ["run", simId, runId] as const,
  evidence: (q: Record<string, unknown>) => ["evidence", q] as const,
  evidenceIds: (scanId: string, ids: string[]) => ["evidence-ids", scanId, ids] as const,
  reports: (scanId: string) => ["reports", scanId] as const,
  report: (id: string) => ["report", id] as const,
  explanations: (scanId: string, fid: string) => ["expl", scanId, fid] as const,
  job: (id: string) => ["job", id] as const,
};

export function useWorkerHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: ({ signal }) => api.get("/health/worker", M.WorkerHealth, { signal, retries: 0, timeoutMs: 8000 }),
    refetchInterval: 30_000,
  });
}

export function useChains() {
  return useQuery({
    queryKey: keys.chains,
    queryFn: ({ signal }) => api.get("/chains", z.array(M.Chain), { signal }),
    staleTime: 5 * 60_000,
  });
}

export type ScanFilter = { chain_id?: number | null; status?: string | null };

export function useScans(offset = 0, limit = 25, filter?: ScanFilter) {
  return useQuery({
    queryKey: [...keys.scans(offset, filter), limit],
    queryFn: ({ signal }) =>
      api.get("/scans", M.page(M.ScanSummary), {
        signal,
        query: { offset, limit, chain_id: filter?.chain_id ?? undefined, status: filter?.status ?? undefined },
      }),
  });
}

/** Polls while the scan is running so the page updates even if SSE is unavailable. */
export function useScan(id: string) {
  return useQuery({
    queryKey: keys.scan(id),
    queryFn: ({ signal }) => api.get(`/scans/${id}`, M.Scan, { signal }),
    refetchInterval: (q) => (q.state.data && !isTerminal(q.state.data.status) ? 3000 : false),
  });
}

export function useFindings(scanId: string, enabled = true) {
  return useQuery({
    queryKey: keys.findings(scanId),
    queryFn: ({ signal }) => api.get(`/scans/${scanId}/findings`, z.array(M.Finding), { signal }),
    enabled,
  });
}

export function useScenarios() {
  return useQuery({
    queryKey: keys.scenarios,
    queryFn: ({ signal }) => api.get("/scenarios", z.array(M.ScenarioDef), { signal }),
    staleTime: Infinity,
  });
}

export function useSimulations(scanId: string, enabled = true) {
  return useQuery({
    queryKey: keys.sims(scanId),
    queryFn: ({ signal }) => api.get(`/scans/${scanId}/simulations`, z.array(M.Simulation), { signal }),
    enabled,
    refetchInterval: (q) => (q.state.data?.some((s) => !isTerminal(s.status)) ? 4000 : false),
  });
}

export function useSimulation(id: string | null) {
  return useQuery({
    queryKey: keys.sim(id ?? ""),
    queryFn: ({ signal }) => api.get(`/simulations/${id}`, M.Simulation, { signal }),
    enabled: !!id,
    refetchInterval: (q) => (q.state.data && !isTerminal(q.state.data.status) ? 3000 : false),
  });
}

export function useScenarioRun(simId: string | null, runId: string | null) {
  return useQuery({
    queryKey: keys.run(simId ?? "", runId ?? ""),
    queryFn: ({ signal }) =>
      api.get(`/simulations/${simId}/runs/${runId}`, M.ScenarioRun, { signal, timeoutMs: 30_000 }),
    enabled: !!simId && !!runId,
  });
}

export interface EvidenceQuery {
  scan_id: string;
  q?: string;
  kind?: string;
  basis?: string;
  function?: string;
  simulation_id?: string;
  offset?: number;
  limit?: number;
}

export function useEvidence(query: EvidenceQuery, enabled = true) {
  return useQuery({
    queryKey: keys.evidence({ ...query }),
    queryFn: ({ signal }) =>
      api.get("/evidence", M.page(M.Evidence), { signal, query: { ...query } as Record<string, string | number> }),
    enabled: enabled && !!query.scan_id,
    placeholderData: (prev) => prev,
  });
}

export function useEvidenceByIds(scanId: string, ids: string[]) {
  return useQuery({
    queryKey: keys.evidenceIds(scanId, ids),
    queryFn: ({ signal }) =>
      api.get("/evidence", M.page(M.Evidence), {
        signal,
        query: { scan_id: scanId, ids: ids.join(","), limit: 100 },
      }),
    enabled: !!scanId && ids.length > 0,
  });
}

export function useReports(scanId: string) {
  return useQuery({
    queryKey: keys.reports(scanId),
    queryFn: ({ signal }) => api.get(`/scans/${scanId}/reports`, z.array(M.Report), { signal }),
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === "rendering") ? 2000 : false),
  });
}

/** Every report in this workspace (GET /reports), newest first. */
export function useWorkspaceReports(offset = 0, limit = 25, chainId?: number | null) {
  return useQuery({
    queryKey: ["reports", "all", offset, limit, chainId ?? null],
    queryFn: ({ signal }) =>
      api.get("/reports", M.page(M.WorkspaceReport), { signal, query: { offset, limit, chain_id: chainId ?? undefined } }),
  });
}

export function useReport(id: string) {
  return useQuery({
    queryKey: keys.report(id),
    queryFn: ({ signal }) => api.get(`/reports/${id}`, M.Report, { signal, timeoutMs: 30_000 }),
    refetchInterval: (q) => (q.state.data?.status === "rendering" ? 2000 : false),
  });
}

export function useExplanations(scanId: string, findingId: string) {
  return useQuery({
    queryKey: keys.explanations(scanId, findingId),
    queryFn: ({ signal }) =>
      api.get(`/scans/${scanId}/findings/${findingId}/explanations`, z.array(M.Explanation), { signal }),
    refetchInterval: (q) => (q.state.data?.some((e) => !isTerminal(e.status)) ? 3000 : false),
  });
}

// ---------------------------------------------------------------- mutations

export function useCreateScan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ScanCreateBody) => api.post("/scans", M.Scan, body),
    onSuccess: (scan) => {
      qc.setQueryData(keys.scan(scan.id), scan);
      void qc.invalidateQueries({ queryKey: ["scans"] });
    },
  });
}

export function useCreateSimulation(scanId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SimulationCreateBody) => api.post(`/scans/${scanId}/simulations`, M.Simulation, body),
    onSuccess: (sim) => {
      qc.setQueryData(keys.sim(sim.id), sim);
      void qc.invalidateQueries({ queryKey: keys.sims(scanId) });
    },
  });
}

export function useCancelJob() {
  return useMutation({
    mutationFn: (jobId: string) => api.post(`/jobs/${jobId}/cancel`, M.Job),
  });
}

export function useCompare() {
  return useMutation({
    mutationFn: (body: CompareBody) => api.post("/positions/compare", M.Compare, body, { timeoutMs: 30_000 }),
  });
}

export function useCreateReport(scanId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ReportCreateBody) => api.post(`/scans/${scanId}/reports`, M.Report, body, { timeoutMs: 30_000 }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.reports(scanId) }),
  });
}

export function useRequestExplanation(scanId: string, findingId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.post(`/scans/${scanId}/findings/${findingId}/explanations`, M.Explanation),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.explanations(scanId, findingId) }),
  });
}

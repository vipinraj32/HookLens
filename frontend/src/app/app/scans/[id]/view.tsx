"use client";

import { useQueryClient } from "@tanstack/react-query";
import { FileDown, FileSearch, FlaskConical, Gauge, X } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useMemo, useState, type ReactNode } from "react";

import { FindingDetail } from "@/components/finding-detail";
import { JobProgress } from "@/components/job-progress";
import { PermissionMatrix } from "@/components/permission-matrix";
import { Tab, TabPanel, Tabs, TabsList } from "@/components/tabs";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHeader,
  EmptyState,
  ErrorState,
  KV,
  Mono,
  Notice,
  PageHeader,
  SeverityBadge,
  Spinner,
  StatusBadge,
  TagBadge,
} from "@/components/ui";
import { isTerminal, keys, useChains, useCreateReport, useFindings, useReports, useScan, useSimulations } from "@/lib/api/hooks";
import { useJobStream } from "@/lib/api/jobs";
import { SEVERITIES, type Finding, type Pool, type Scan } from "@/lib/api/models";
import { cn, formatDate, groupDecimal, humanize } from "@/lib/format";

const SEV_ORDER = Object.fromEntries(SEVERITIES.map((s, i) => [s, i]));

function SeveritySummary({ scan }: { scan: Scan }) {
  const by = scan.summary.by_severity ?? {};
  return (
    <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
      {SEVERITIES.map((s) => (
        <div key={s} className="rounded-lg border border-line bg-surface px-3 py-2.5">
          <p className="text-[11px] uppercase tracking-wide text-faint">{s === "informational" ? "info" : s}</p>
          <p className={cn("mt-0.5 text-xl font-semibold tabular-nums", (by[s] ?? 0) === 0 && "text-faint")}>{by[s] ?? 0}</p>
        </div>
      ))}
    </div>
  );
}

function FindingsPanel({ scan, initial }: { scan: Scan; initial: string | null }) {
  const findings = useFindings(scan.id, isTerminal(scan.status));
  const [sev, setSev] = useState<string>("all");
  const [basis, setBasis] = useState<string>("all");
  const [q, setQ] = useState("");
  const [selected, setSelected] = useState<string | null>(initial);

  const list = useMemo(() => {
    const items = [...(findings.data ?? [])].sort(
      (a, b) => (SEV_ORDER[a.severity] ?? 9) - (SEV_ORDER[b.severity] ?? 9) || a.title.localeCompare(b.title),
    );
    const needle = q.trim().toLowerCase();
    return items.filter(
      (f) =>
        (sev === "all" || f.severity === sev) &&
        (basis === "all" || f.confidence_basis === basis) &&
        (!needle ||
          f.title.toLowerCase().includes(needle) ||
          f.finding_id.toLowerCase().includes(needle) ||
          f.rule_id.toLowerCase().includes(needle) ||
          f.affected_functions.some((fn) => fn.toLowerCase().includes(needle))),
    );
  }, [findings.data, sev, basis, q]);
  const bases = useMemo(() => [...new Set((findings.data ?? []).map((f) => f.confidence_basis))], [findings.data]);
  const current: Finding | undefined = findings.data?.find((f) => f.finding_id === selected);

  if (!isTerminal(scan.status)) return <Spinner label="Findings appear when the scan finishes…" />;
  if (findings.isPending) return <Spinner label="Loading findings…" />;
  if (findings.isError) return <ErrorState error={findings.error} onRetry={() => findings.refetch()} />;
  if (findings.data.length === 0) {
    return (
      <EmptyState title="No findings">
        The analyzers that ran produced no findings. This does not establish that the hook is safe; check the analyzer
        coverage tab for anything that was skipped.
      </EmptyState>
    );
  }

  return (
    <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <div className="flex min-w-0 flex-col gap-3">
        <div className="flex flex-wrap gap-2">
          <label className="flex items-center gap-2 text-xs text-muted">
            Severity
            <select value={sev} onChange={(e) => setSev(e.target.value)} className="h-8 rounded-md border border-line bg-bg px-2 text-sm text-fg">
              <option value="all">All</option>
              {SEVERITIES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs text-muted">
            Basis
            <select value={basis} onChange={(e) => setBasis(e.target.value)} className="h-8 rounded-md border border-line bg-bg px-2 text-sm text-fg">
              <option value="all">All</option>
              {bases.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
            </select>
          </label>
          <input
            type="search"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search title, ID, rule, function…"
            aria-label="Search findings"
            className="h-8 min-w-48 flex-1 rounded-md border border-line bg-bg px-2 text-sm text-fg"
          />
          <span className="ml-auto self-center text-xs text-faint">
            {list.length} of {findings.data.length}
          </span>
        </div>
        <ul className="flex flex-col gap-2">
          {list.map((f) => (
            <li key={f.finding_id}>
              <button
                type="button"
                onClick={() => setSelected(f.finding_id)}
                aria-pressed={selected === f.finding_id}
                className={cn(
                  "flex w-full flex-col gap-1.5 rounded-lg border border-line bg-surface p-3 text-left hover:border-accent/50",
                  selected === f.finding_id && "border-accent/70 bg-surface-2",
                )}
              >
                <span className="flex flex-wrap items-center gap-1.5">
                  <SeverityBadge severity={f.severity} />
                  <StatusBadge status={f.status} />
                  <TagBadge tag={f.confidence_basis} />
                </span>
                <span className="text-sm font-medium text-fg">{f.title}</span>
                <span className="font-mono text-[11px] text-faint">
                  {f.finding_id} · {humanize(f.category)}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div className="min-w-0">
        {current ? (
          <Card className="sticky top-4">
            <div className="flex justify-end px-3 pt-3">
              <Button size="icon" variant="ghost" aria-label="Close finding" onClick={() => setSelected(null)}>
                <X aria-hidden="true" className="size-4" />
              </Button>
            </div>
            <CardBody className="pt-0">
              <FindingDetail f={current} />
            </CardBody>
          </Card>
        ) : (
          <Card className="hidden xl:block">
            <EmptyState title="Select a finding">See its rationale, LP implication, evidence and an optional explanation.</EmptyState>
          </Card>
        )}
      </div>
    </div>
  );
}

function PoolCard({ pool, scanId }: { pool: Pool; scanId: string }) {
  const s = pool.state;
  const t0 = pool.token0?.symbol ?? "token0";
  const t1 = pool.token1?.symbol ?? "token1";
  return (
    <Card>
      <CardHeader
        title={`${t0} / ${t1}`}
        description={<Mono value={pool.pool_id} short />}
        actions={
          <Button size="sm" asChild>
            <Link href={`/app/lp?scan=${scanId}&pool=${pool.pool_id}`}>
              <Gauge aria-hidden="true" className="size-3.5" /> LP exposure
            </Link>
          </Button>
        }
      />
      <CardBody>
        <KV
          items={[
            ["Fee", pool.dynamic_fee ? `dynamic (current LP fee ${s?.lp_fee ?? "?"} pips)` : `${pool.fee} pips (${pool.fee / 10_000}%)`],
            ["Tick spacing", pool.tick_spacing],
            ["State", s ? (s.initialized ? <TagBadge tag="on-chain" /> : "not initialized") : "unavailable"],
            ["Current tick", s?.tick ?? "—"],
            ["Active liquidity", s?.liquidity ? groupDecimal(s.liquidity) : "—"],
            ["Read at block", s?.block_number ?? "—"],
            ["Token0", <span key="t0">{t0} <Mono value={pool.currency0} short /> {pool.token0?.decimals ?? "?"} dec</span>],
            ["Token1", <span key="t1">{t1} <Mono value={pool.currency1} short /> {pool.token1?.decimals ?? "?"} dec</span>],
            ["Initialized", pool.init_block ? `block ${pool.init_block}` : "—"],
          ]}
        />
      </CardBody>
    </Card>
  );
}

function PoolsPanel({ scan }: { scan: Scan }) {
  const d = scan.analysis.discovery as
    | { status?: string; reason?: string | null; from_block?: number; scanned_to?: number; source?: string; notes?: string[] }
    | null
    | undefined;
  return (
    <div className="flex flex-col gap-4">
      {d ? (
        <div className="flex flex-col gap-1 text-xs text-muted">
          <p>
            Pool discovery: <StatusBadge status={d.status ?? "unknown"} /> scanned blocks {d.from_block ?? "?"}–{d.scanned_to ?? "?"}
            {d.source === "etherscan" ? " via Etherscan" : d.source === "rpc" ? " via RPC" : ""}
            {d.reason ? ` · ${d.reason}` : ""}
          </p>
          {(d.notes ?? []).map((n) => (
            <p key={n}>{n}</p>
          ))}
        </div>
      ) : null}
      {scan.pools.length === 0 ? (
        <EmptyState title="No pools found">
          No initialized pool using this hook was found in the scanned range. Simulations and LP exposure need a pool.
        </EmptyState>
      ) : (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {scan.pools.map((p) => (
            <PoolCard key={p.pool_id} pool={p} scanId={scan.id} />
          ))}
        </div>
      )}
    </div>
  );
}

function ContractPanel({ scan }: { scan: Scan }) {
  const c = scan.contract;
  const src = scan.analysis.source as { contract_path?: string; file_count?: number; provider?: string } | null | undefined;
  if (!c) return <EmptyState title="Contract not resolved" />;
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader title="Identity" />
        <CardBody>
          <KV
            items={[
              ["Address", <Mono key="a" value={c.address} />],
              ["Name", c.contract_name ?? "unknown"],
              ["Source", <span key="s" className="flex flex-wrap items-center gap-2"><StatusBadge status={c.source_status} />{src?.contract_path ? <span className="font-mono text-xs text-muted">{src.contract_path}</span> : null}</span>],
              ["Compiler", c.compiler_version ?? "—"],
              ["Code size", `${c.code_size.toLocaleString()} bytes`],
              ["Runtime code hash", <Mono key="h" value={c.runtime_code_hash} short />],
            ]}
          />
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Provenance" description="Everything was read at this pinned block." />
        <CardBody>
          <KV
            items={[
              ["Chain", c.chain_id],
              ["Block", c.block_number],
              ["Block hash", <Mono key="bh" value={c.block_hash} short />],
              ["Proxy", c.is_proxy ? `${c.proxy_kind ?? "yes"}` : "no"],
              ...(c.is_proxy
                ? ([
                    ["Implementation", <Mono key="i" value={c.implementation_address} />],
                    ["Impl. code hash", <Mono key="ih" value={c.implementation_code_hash} short />],
                    ["Proxy admin", <Mono key="pa" value={c.proxy_admin} />],
                  ] as [string, ReactNode][])
                : []),
            ]}
          />
        </CardBody>
      </Card>
    </div>
  );
}

function AnalyzersPanel({ scan }: { scan: Scan }) {
  const runs = scan.analysis.runs ?? [];
  const caps = scan.analysis.capabilities as { unavailable?: { capability?: string; reason?: string }[] | string[] } | null | undefined;
  return (
    <div className="flex flex-col gap-4">
      {caps?.unavailable?.length ? (
        <Notice tone="warn">
          Some analysis was unavailable:{" "}
          {caps.unavailable.map((u) => (typeof u === "string" ? u : `${u.capability}: ${u.reason}`)).join("; ")}
        </Notice>
      ) : null}
      <div className="overflow-x-auto rounded-lg border border-line">
        <table className="w-full min-w-[560px] text-sm">
          <thead className="bg-surface text-left text-xs uppercase tracking-wide text-faint">
            <tr>
              <th scope="col" className="px-4 py-2 font-medium">Analyzer</th>
              <th scope="col" className="px-3 py-2 font-medium">Status</th>
              <th scope="col" className="px-3 py-2 font-medium">Findings</th>
              <th scope="col" className="px-4 py-2 font-medium">Note</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.analyzer_id} className="border-t border-line/60">
                <td className="px-4 py-2 font-mono text-xs">{r.analyzer_id}</td>
                <td className="px-3 py-2">
                  <StatusBadge status={r.status} />
                </td>
                <td className="px-3 py-2 tabular-nums">{r.findings ?? 0}</td>
                <td className="px-4 py-2 text-xs text-muted">{r.reason ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {scan.analysis.analyzer_version ? <p className="text-xs text-faint">{scan.analysis.analyzer_version}</p> : null}
    </div>
  );
}

function ReportsPanel({ scan }: { scan: Scan }) {
  const reports = useReports(scan.id);
  const sims = useSimulations(scan.id);
  const create = useCreateReport(scan.id);
  const finishedSims = (sims.data ?? []).filter((s) => isTerminal(s.status));
  const [simId, setSimId] = useState<string>("");
  const chosen = simId || finishedSims[0]?.id || "";
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader title="Generate report" description="Versioned JSON with a content hash, plus a PDF rendering." />
        <CardBody className="flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1.5 text-sm">
            Include simulation
            <select value={chosen} onChange={(e) => setSimId(e.target.value)} className="h-10 min-w-64 rounded-md border border-line bg-bg px-3 text-sm">
              <option value="">None (static analysis only)</option>
              {finishedSims.map((s) => (
                <option key={s.id} value={s.id}>
                  {formatDate(s.created_at)} · {s.status}
                </option>
              ))}
            </select>
          </label>
          <Button variant="primary" loading={create.isPending} onClick={() => create.mutate({ simulation_id: chosen || null })}>
            <FileDown aria-hidden="true" className="size-4" /> Generate
          </Button>
          {create.isError ? <ErrorState error={create.error} title="Report failed" /> : null}
        </CardBody>
      </Card>
      {reports.isError ? <ErrorState error={reports.error} onRetry={() => reports.refetch()} /> : null}
      {reports.data?.length ? (
        <ul className="flex flex-col gap-2">
          {reports.data.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-3 rounded-lg border border-line bg-surface px-4 py-3 text-sm">
              <Link href={`/app/reports/${r.id}`} className="text-accent hover:underline">
                Report {formatDate(r.created_at)}
              </Link>
              <StatusBadge status={r.status} />
              <span className="font-mono text-xs text-faint">{r.content_hash.slice(0, 23)}…</span>
              {r.simulation_id ? <Badge className="text-ok">with simulation</Badge> : null}
            </li>
          ))}
        </ul>
      ) : reports.isPending ? null : (
        <p className="text-sm text-muted">No reports yet.</p>
      )}
    </div>
  );
}

export function ScanView() {
  const { id } = useParams<{ id: string }>();
  const qc = useQueryClient();
  const scan = useScan(id);
  const chains = useChains();
  const params = useSearchParams();
  const router = useRouter();
  const initialFinding = params.get("finding");
  const tab = params.get("tab") ?? "findings";
  const findings = useFindings(id, scan.data ? isTerminal(scan.data.status) : false);
  const running = scan.data ? !isTerminal(scan.data.status) : false;
  const stream = useJobStream(running ? scan.data?.job_id : null, () => {
    void qc.invalidateQueries({ queryKey: keys.scan(id) });
    void qc.invalidateQueries({ queryKey: keys.findings(id) });
  });

  if (scan.isPending) return <Spinner label="Loading scan…" />;
  if (scan.isError) return <ErrorState error={scan.error} onRetry={() => scan.refetch()} title="Could not load scan" />;
  const s = scan.data;
  const chain = chains.data?.find((c) => c.chain_id === s.chain_id);

  return (
    <>
      <PageHeader
        eyebrow="Hook intelligence"
        title={s.contract?.contract_name ?? "Hook"}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Mono value={s.hook_address} />
            <span className="text-faint">·</span>
            <span>{chain?.name ?? `chain ${s.chain_id}`}</span>
            {s.contract ? (
              <>
                <span className="text-faint">·</span>
                <span>block {s.contract.block_number}</span>
              </>
            ) : null}
            <StatusBadge status={s.status} />
          </span>
        }
        actions={
          <>
            <Button asChild variant="primary">
              <Link href={`/app/scans/${s.id}/lab`}>
                <FlaskConical aria-hidden="true" className="size-4" /> Adversarial lab
              </Link>
            </Button>
            <Button asChild>
              <Link href={`/app/lp?scan=${s.id}`}>
                <Gauge aria-hidden="true" className="size-4" /> LP exposure
              </Link>
            </Button>
            <Button asChild>
              <Link href={`/app/evidence?scan=${s.id}`}>
                <FileSearch aria-hidden="true" className="size-4" /> Evidence
              </Link>
            </Button>
          </>
        }
      />

      {running && s.job_id ? (
        <Card className="mb-6">
          <CardBody>
            <JobProgress jobId={s.job_id} stream={stream} title="Scan" />
          </CardBody>
        </Card>
      ) : null}
      {s.error ? (
        <div className="mb-6">
          <ErrorState
            title={`Scan ${s.status}`}
            error={new Error(String((s.error as { message?: string }).message ?? JSON.stringify(s.error)))}
          />
        </div>
      ) : null}
      {s.status === "partial" ? (
        <Notice tone="warn" className="mb-6">
          This scan is partial: at least one analyzer failed or was skipped. See the Analyzers tab.
        </Notice>
      ) : null}

      <div className="mb-6">
        <SeveritySummary scan={s} />
      </div>

      <Tabs value={tab} onValueChange={(v) => router.replace(`/app/scans/${s.id}?tab=${v}`, { scroll: false })}>
        <TabsList aria-label="Scan sections">
          <Tab value="findings">Findings{s.summary.finding_count !== undefined ? ` (${s.summary.finding_count})` : ""}</Tab>
          <Tab value="permissions">Permission matrix</Tab>
          <Tab value="pools">Pools ({s.pools.length})</Tab>
          <Tab value="contract">Contract</Tab>
          <Tab value="analyzers">Analyzers</Tab>
          <Tab value="reports">Reports</Tab>
        </TabsList>
        <TabPanel value="findings">
          <FindingsPanel key={initialFinding ?? ""} scan={s} initial={initialFinding} />
        </TabPanel>
        <TabPanel value="permissions">
          <PermissionMatrix scan={s} findings={findings.data} />
        </TabPanel>
        <TabPanel value="pools">
          <PoolsPanel scan={s} />
        </TabPanel>
        <TabPanel value="contract">
          <ContractPanel scan={s} />
        </TabPanel>
        <TabPanel value="analyzers">
          <AnalyzersPanel scan={s} />
        </TabPanel>
        <TabPanel value="reports">
          <ReportsPanel scan={s} />
        </TabPanel>
      </Tabs>
    </>
  );
}

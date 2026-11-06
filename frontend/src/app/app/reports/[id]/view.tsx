"use client";

import { ArrowLeft, Braces, FileText } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { Badge, Button, Card, CardBody, CardHeader, CodeBlock, CopyButton, ErrorState, KV, Mono, Notice, PageHeader, SeverityBadge, Spinner, StatusBadge, TagBadge } from "@/components/ui";
import { apiUrl } from "@/lib/api/client";
import { useReport } from "@/lib/api/hooks";
import { SEVERITIES } from "@/lib/api/models";
import { cn, formatDate, formatDuration, groupDecimal, humanize } from "@/lib/format";

interface RFinding {
  finding_id: string;
  title: string;
  severity: string;
  status: string;
  confidence_basis: string;
  description: string;
  lp_implications?: string;
  evidence_ids?: string[];
}
interface RRun {
  scenario_id: string;
  status: string;
  status_reason: string;
  duration_ms?: number | null;
  repro_command?: string;
}
interface Content {
  report_version: string;
  generator: string;
  generated_at: string;
  identity: Record<string, string | number | boolean | null>;
  summary: { finding_count?: number; by_severity?: Record<string, number> };
  findings: RFinding[];
  simulation?: { simulation_id: string; status: string; fork_block?: number; harness?: { version?: string; digest?: string }; runs: RRun[] } | null;
  lp_exposure?: {
    position?: { tick_lower: number; tick_upper: number; liquidity: string };
    baseline?: Record<string, { value: string | number | null; tag: string }>;
    pool?: { token1?: { symbol?: string } };
  } | null;
  assumptions?: string[];
  limitations?: string[];
  reproduction?: { scan?: string; scenarios?: string[] };
  disclaimer: string;
}

function downloadJson(name: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function ReportFindings({ findings, scanId }: { findings: RFinding[]; scanId: string }) {
  const [q, setQ] = useState("");
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const counts = useMemo(() => {
    const m: Record<string, number> = {};
    for (const f of findings) m[f.severity] = (m[f.severity] ?? 0) + 1;
    return m;
  }, [findings]);
  const needle = q.trim().toLowerCase();
  const list = findings.filter(
    (f) =>
      !hidden.has(f.severity) &&
      (!needle ||
        f.title.toLowerCase().includes(needle) ||
        f.finding_id.toLowerCase().includes(needle) ||
        f.description.toLowerCase().includes(needle)),
  );
  return (
    <Card className="mt-6">
      <CardHeader
        title={`Findings (${findings.length})`}
        description="Static indicators for review, not confirmed exploits."
      />
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-5 py-3">
        {SEVERITIES.filter((s) => counts[s]).map((s) => (
          <button
            key={s}
            type="button"
            aria-pressed={!hidden.has(s)}
            onClick={() => {
              const next = new Set(hidden);
              if (next.has(s)) next.delete(s);
              else next.add(s);
              setHidden(next);
            }}
            className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs", hidden.has(s) ? "border-line text-faint line-through" : "border-line text-fg hover:border-line-strong")}
          >
            {s} <span className="tabular-nums text-muted">{counts[s]}</span>
          </button>
        ))}
        <input
          type="search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search findings…"
          aria-label="Search findings"
          className="ml-auto h-8 min-w-48 rounded-md border border-line bg-bg px-2 text-sm"
        />
        <span className="text-xs text-faint">
          {list.length} shown
        </span>
      </div>
      {list.length === 0 ? (
        <p className="px-5 py-4 text-sm text-muted">No finding matches these filters.</p>
      ) : (
        <ul className="divide-y divide-line/60">
          {list.map((f) => (
            <li key={f.finding_id} className="flex flex-col gap-1.5 px-5 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <SeverityBadge severity={f.severity} />
                <StatusBadge status={f.status} />
                <TagBadge tag={f.confidence_basis} />
                <span className="inline-flex items-center gap-1 font-mono text-xs text-faint">
                  {f.finding_id}
                  <CopyButton value={f.finding_id} label="Copy ID" />
                </span>
              </div>
              <p className="text-sm font-medium">{f.title}</p>
              <p className="text-sm text-muted">{f.description}</p>
              {f.lp_implications ? <p className="text-sm text-warn/90">LP: {f.lp_implications}</p> : null}
              <p className="flex flex-wrap gap-3 text-xs">
                <Link href={`/app/scans/${scanId}?finding=${f.finding_id}`} className="text-accent hover:underline">
                  Open finding with evidence
                </Link>
                {f.evidence_ids?.length ? <span className="text-faint">{f.evidence_ids.length} evidence item{f.evidence_ids.length === 1 ? "" : "s"}</span> : null}
              </p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function ReportView() {
  const { id } = useParams<{ id: string }>();
  const rep = useReport(id);
  if (rep.isPending) return <Spinner label="Loading report…" />;
  if (rep.isError) return <ErrorState error={rep.error} onRetry={() => rep.refetch()} title="Could not load report" />;
  const r = rep.data;
  const c = r.content as unknown as Content | undefined;
  if (!c) return <ErrorState error={new Error("The report has no content.")} />;
  const idn = c.identity;
  const lp = c.lp_exposure;
  const unit = lp?.pool?.token1?.symbol ?? "token1";

  return (
    <>
      <PageHeader
        eyebrow="Report"
        title={String(idn.contract_name ?? "Hook report")}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <Mono value={String(idn.hook_address)} /> · chain {String(idn.chain_id)} · block {String(idn.block_number)} ·{" "}
            {formatDate(c.generated_at)}
          </span>
        }
        actions={
          <>
            <Button asChild>
              <Link href={`/app/scans/${r.scan_id}`}>
                <ArrowLeft aria-hidden="true" className="size-4" /> Scan
              </Link>
            </Button>
            <Button onClick={() => downloadJson(`hooklens-report-${r.id}.json`, { ...c, content_hash: r.content_hash })}>
              <Braces aria-hidden="true" className="size-4" /> JSON
            </Button>
            {r.pdf_available ? (
              <Button asChild variant="primary">
                <a href={apiUrl(`/reports/${r.id}/pdf`)} download>
                  <FileText aria-hidden="true" className="size-4" /> PDF
                </a>
              </Button>
            ) : (
              <Button variant="primary" disabled loading={r.status === "rendering"}>
                <FileText aria-hidden="true" className="size-4" /> {r.status === "rendering" ? "Rendering PDF…" : "PDF unavailable"}
              </Button>
            )}
          </>
        }
      />

      <section aria-label="Assumptions and limitations" className="mb-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <Card className="border-warn/30">
          <CardHeader title="Assumptions" />
          <CardBody>
            {(c.assumptions ?? []).length ? (
              <ul className="list-disc pl-5 text-sm text-muted">{(c.assumptions ?? []).map((a, i) => <li key={i}>{a}</li>)}</ul>
            ) : (
              <p className="text-sm text-faint">None recorded.</p>
            )}
          </CardBody>
        </Card>
        <Card className="border-warn/30">
          <CardHeader title="Limitations" description="Read before relying on results." />
          <CardBody>
            {(c.limitations ?? []).length ? (
              <ul className="list-disc pl-5 text-sm text-muted">{(c.limitations ?? []).map((a, i) => <li key={i}>{a}</li>)}</ul>
            ) : (
              <p className="text-sm text-faint">None recorded.</p>
            )}
          </CardBody>
        </Card>
      </section>

      <Notice className="mb-6">{c.disclaimer}</Notice>
      {r.status === "pdf_failed" ? <Notice tone="warn" className="mb-6">The PDF failed to render; the JSON report is complete.</Notice> : null}

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader title="Identity & provenance" />
          <CardBody>
            <KV
              items={[
                ["Hook", <Mono key="h" value={String(idn.hook_address)} />],
                ["Block hash", <Mono key="bh" value={String(idn.block_hash)} short />],
                ["Code hash", <Mono key="ch" value={String(idn.runtime_code_hash)} short />],
                ["Source", <StatusBadge key="s" status={String(idn.source_status)} />],
                ["Compiler", String(idn.compiler_version ?? "—")],
                ["Proxy", idn.is_proxy ? `yes → ${String(idn.implementation)}` : "no"],
              ]}
            />
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Report integrity" />
          <CardBody>
            <KV
              items={[
                ["Version", c.report_version],
                ["Generator", c.generator],
                ["Content hash", <Mono key="hash" value={r.content_hash} short />],
                ["Status", <StatusBadge key="st" status={r.status} />],
              ]}
            />
            <p className="mt-3 text-xs text-faint">The hash covers the canonical JSON content excluding the generation timestamp.</p>
          </CardBody>
        </Card>
      </div>

      <ReportFindings findings={c.findings} scanId={r.scan_id} />

      {c.simulation ? (
        <Card className="mt-6">
          <CardHeader
            title="Simulation"
            description={`Fork block ${c.simulation.fork_block ?? "?"} · ${c.simulation.harness?.version ?? ""}`}
            actions={<StatusBadge status={c.simulation.status} />}
          />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[600px] text-sm">
              <tbody>
                {[...c.simulation.runs].sort((a, b) => a.status.localeCompare(b.status)).map((run) => (
                  <tr key={run.scenario_id} className="border-t border-line/60">
                    <td className="px-5 py-2.5">{humanize(run.scenario_id)}</td>
                    <td className="px-3 py-2.5">
                      <StatusBadge status={run.status} />
                    </td>
                    <td className="px-3 py-2.5 text-xs text-muted">{run.status_reason}</td>
                    <td className="whitespace-nowrap px-5 py-2.5 text-right text-xs text-faint">
                      {formatDuration(run.duration_ms)}
                      {run.repro_command ? <span className="ml-2"><CopyButton value={run.repro_command} label="Copy repro" /></span> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}

      {lp?.baseline ? (
        <Card className="mt-6">
          <CardHeader
            title="LP exposure"
            description={lp.position ? `Ticks [${lp.position.tick_lower}, ${lp.position.tick_upper}) · L = ${groupDecimal(lp.position.liquidity)}` : undefined}
          />
          <CardBody className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {Object.entries(lp.baseline).map(([k, v]) => (
              <div key={k} className="flex items-center justify-between gap-2 rounded-md border border-line px-3 py-2 text-sm">
                <span className="text-muted">{humanize(k)}</span>
                <span className="flex items-center gap-2 font-mono text-xs">
                  {v.value === null ? "—" : typeof v.value === "string" && /^-?\d/.test(v.value) ? groupDecimal(v.value) : String(v.value)}
                  {k === "value_in_token1" ? ` ${unit}` : ""}
                  <TagBadge tag={v.tag} />
                </span>
              </div>
            ))}
          </CardBody>
        </Card>
      ) : null}

      {c.reproduction ? (
        <Card className="mt-6">
          <CardHeader title="Reproduction" description="Use your own RPC endpoint." />
          <CardBody className="flex flex-col gap-3">
            {c.reproduction.scan ? <CodeBlock code={c.reproduction.scan} /> : null}
            {(c.reproduction.scenarios ?? []).map((cmd, i) => (
              <CodeBlock key={i} code={cmd} />
            ))}
          </CardBody>
        </Card>
      ) : null}
      <p className="mt-6 text-xs text-faint">
        <Badge className="mr-2">report {r.id}</Badge>
        Created {formatDate(r.created_at)}
      </p>
    </>
  );
}

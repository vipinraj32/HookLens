"use client";

import { Providers } from "@/components/providers";
import { useChains, useScenarios, useWorkerHealth } from "@/lib/api/hooks";
import { cn } from "@/lib/format";

/**
 * Live facts from this HookLens server, as one compact row: chains with RPC status, Foundry, and
 * the scenario count. Nothing is shown for data the server did not return.
 */
function Pill({ ok, children, title }: { ok?: boolean; children: React.ReactNode; title?: string }) {
  return (
    <li title={title} className="inline-flex items-center gap-1.5 rounded-full border border-line bg-surface/70 px-2.5 py-1">
      {ok !== undefined ? <span aria-hidden="true" className={cn("size-1.5 rounded-full", ok ? "bg-ok" : "bg-faint")} /> : null}
      {children}
    </li>
  );
}

function Inner() {
  const chains = useChains();
  const health = useWorkerHealth();
  const scenarios = useScenarios();

  if (chains.isPending && health.isPending) return <p className="text-xs text-faint">Checking server…</p>;
  if (chains.isError && health.isError) return <p className="text-xs text-faint">Server status unavailable.</p>;

  return (
    <ul aria-label="Live server status" className="flex flex-wrap gap-1.5 text-xs text-muted">
      {chains.data?.map((c) => (
        <Pill key={c.chain_id} ok={c.rpc_configured} title={c.rpc_configured ? "RPC configured" : "No RPC configured"}>
          {c.name}
        </Pill>
      ))}
      {health.data ? <Pill ok={health.data.forge.available}>Foundry</Pill> : null}
      {scenarios.data ? (
        <Pill>
          <span className="font-semibold tabular-nums text-fg">{scenarios.data.length}</span> fork scenarios
        </Pill>
      ) : null}
    </ul>
  );
}

export function LiveStatus() {
  return (
    <Providers>
      <Inner />
    </Providers>
  );
}

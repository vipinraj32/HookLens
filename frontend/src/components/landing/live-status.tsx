"use client";

import { Providers } from "@/components/providers";
import { useChains, useScenarios, useWorkerHealth } from "@/lib/api/hooks";
import { cn } from "@/lib/format";

/**
 * Live facts read from this HookLens server: configured chains, Foundry availability and the
 * number of fork scenarios. Nothing is rendered for data the server did not return; there is
 * no "latest indexed block" because HookLens does not run an indexer.
 */
function Inner() {
  const chains = useChains();
  const health = useWorkerHealth();
  const scenarios = useScenarios();

  if (chains.isPending && health.isPending) {
    return <p className="text-xs text-faint">Checking this HookLens server…</p>;
  }
  if (chains.isError && health.isError) {
    return (
      <p className="text-xs text-faint">
        The HookLens API is not reachable from this page, so no live server status is shown.
      </p>
    );
  }

  return (
    <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)_minmax(0,1fr)]">
      {chains.data ? (
        <div className="rounded-xl border border-line bg-surface/70 p-3">
          <dt className="text-xs text-faint">Chains on this server</dt>
          <dd className="mt-1.5 flex flex-col gap-1">
            {chains.data.map((c) => (
              <span key={c.chain_id} className="flex items-center gap-2">
                <span aria-hidden="true" className={cn("size-1.5 rounded-full", c.rpc_configured ? "bg-ok" : "bg-faint")} />
                <span className="min-w-0 truncate" title={c.name}>{c.name}</span>
                <span className="ml-auto whitespace-nowrap text-xs text-faint">{c.rpc_configured ? "RPC ready" : "no RPC"}</span>
              </span>
            ))}
          </dd>
        </div>
      ) : null}
      {health.data ? (
        <div className="rounded-xl border border-line bg-surface/70 p-3">
          <dt className="text-xs text-faint">Fork simulations</dt>
          <dd className="mt-1.5 flex items-center gap-2">
            <span aria-hidden="true" className={cn("size-1.5 rounded-full", health.data.forge.available ? "bg-ok" : "bg-warn")} />
            {health.data.forge.available ? "Foundry available" : "Foundry not installed"}
          </dd>
          <dd className="mt-1 flex items-center gap-2 text-xs text-faint">
            AI explanations {health.data.ai.enabled ? "on" : "off"}
          </dd>
        </div>
      ) : null}
      {scenarios.data ? (
        <div className="rounded-xl border border-line bg-surface/70 p-3">
          <dt className="text-xs text-faint">Adversarial scenarios</dt>
          <dd className="mt-1 text-xl font-semibold tabular-nums">{scenarios.data.length}</dd>
          <dd className="text-xs text-faint">run with Foundry on a fork</dd>
        </div>
      ) : null}
    </dl>
  );
}

export function LiveStatus() {
  return (
    <Providers>
      <Inner />
    </Providers>
  );
}

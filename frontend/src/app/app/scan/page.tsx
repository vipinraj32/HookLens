"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { JobProgress } from "@/components/job-progress";
import { Badge, Button, Card, CardBody, CardHeader, ErrorState, Field, Notice, PageHeader, inputClass } from "@/components/ui";
import { api, errorMessage } from "@/lib/api/client";
import { keys, useChains, useCreateScan } from "@/lib/api/hooks";
import { useJobStream } from "@/lib/api/jobs";
import { Permissions } from "@/lib/api/models";
import { useNetwork } from "@/lib/network";

const ADDRESS = /^0x[0-9a-fA-F]{40}$/;

const schema = z.object({
  chain_id: z.coerce.number<string>().int(),
  hook_address: z
    .string()
    .trim()
    .regex(ADDRESS, "Enter a 20-byte hex address starting with 0x.")
    .refine((a) => !/^0x0{40}$/i.test(a), "The zero address is not a hook."),
  pool_id: z
    .string()
    .trim()
    .regex(/^(0x[0-9a-fA-F]{64})?$/, "A v4 pool ID is 32 bytes: 0x followed by 64 hex characters.")
    .optional(),
  block_number: z
    .string()
    .trim()
    .regex(/^\d*$/, "Block number must be a whole number.")
    .optional(),
  discover_pools: z.boolean(),
});
type FormIn = z.input<typeof schema>;
type FormOut = z.output<typeof schema>;

const DecodeResult = Permissions.extend({ valid_hook_address: z.boolean(), validity_reason: z.string() });

function PermissionPreview({ address }: { address: string }) {
  const ok = ADDRESS.test(address);
  const q = useQuery({
    queryKey: ["decode", address.toLowerCase()],
    queryFn: ({ signal }) => api.get("/permissions/decode", DecodeResult, { signal, query: { address } }),
    enabled: ok,
    staleTime: Infinity,
  });
  if (!ok) return null;
  if (q.isError) return <p className="text-xs text-bad">Could not decode permission bits: {errorMessage(q.error)}</p>;
  if (!q.data) return <p className="text-xs text-faint">Decoding permission bits…</p>;
  const d = q.data;
  return (
    <div className="rounded-lg border border-line bg-bg p-3 text-xs">
      <p className="mb-2 text-faint">
        Address bits <span className="font-mono text-fg">{d.bits}</span> (decoded locally from the address; not yet
        checked on-chain)
      </p>
      {d.enabled_flags.length ? (
        <div className="flex flex-wrap gap-1">
          {d.enabled_flags.map((f) => (
            <Badge key={f} className="font-mono text-fg">
              {f}
            </Badge>
          ))}
        </div>
      ) : (
        <p className="text-muted">No permission bits are set: the PoolManager will not call this address as a hook.</p>
      )}
      {!d.valid_hook_address ? <p className="mt-2 text-warn">Not a valid hook address: {d.validity_reason}</p> : null}
    </div>
  );
}

export default function ScanPage() {
  const id = useId();
  const router = useRouter();
  const qc = useQueryClient();
  const chains = useChains();
  const create = useCreateScan();
  const [scanId, setScanId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  const form = useForm<FormIn, unknown, FormOut>({
    resolver: zodResolver(schema),
    mode: "onTouched",
    defaultValues: { chain_id: "31337", hook_address: "", pool_id: "", block_number: "", discover_pools: true },
  });
  const [network] = useNetwork();
  // Pre-select the header's network once chains are known, unless the user already picked one.
  useEffect(() => {
    if (network === null || form.formState.dirtyFields.chain_id) return;
    if (chains.data?.some((c) => c.chain_id === network)) form.setValue("chain_id", String(network));
  }, [network, chains.data, form]);
  const address = useWatch({ control: form.control, name: "hook_address" }) ?? "";
  const chainId = Number(useWatch({ control: form.control, name: "chain_id" }));
  const chain = chains.data?.find((c) => c.chain_id === chainId);

  const stream = useJobStream(jobId, (status) => {
    if (!scanId) return;
    void qc.invalidateQueries({ queryKey: keys.scan(scanId) });
    if (status === "succeeded") router.push(`/app/scans/${scanId}`);
  });

  const onSubmit = form.handleSubmit((v) => {
    create.mutate(
      {
        chain_id: v.chain_id,
        hook_address: v.hook_address,
        pool_id: v.pool_id ? v.pool_id : null,
        block_number: v.block_number ? Number(v.block_number) : null,
        discover_pools: v.discover_pools,
      },
      {
        onSuccess: (scan) => {
          setScanId(scan.id);
          setJobId(scan.job_id ?? null);
        },
      },
    );
  });

  const err = form.formState.errors;
  const fid = (n: string) => `${id}-${n}`;
  const describedBy = (n: string, hint = true) =>
    [hint ? `${fid(n)}-hint` : null, err[n as keyof FormIn] ? `${fid(n)}-error` : null].filter(Boolean).join(" ") || undefined;

  return (
    <>
      <PageHeader
        eyebrow="Hook Scanner"
        title="Scan a Uniswap v4 hook"
        description="Paste a deployed hook. No wallet needed."
      />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Card>
          <CardHeader title="Target" />
          <CardBody>
            <form noValidate onSubmit={onSubmit} className="flex flex-col gap-5">
              <Field id={fid("chain")} label="Chain" hint="RPC endpoints are configured on the server; you cannot supply one.">
                <select id={fid("chain")} className={inputClass} aria-describedby={`${fid("chain")}-hint`} {...form.register("chain_id")}>
                  {(chains.data ?? [{ chain_id: 31337, name: "Local Anvil", rpc_configured: true }]).map((c) => (
                    <option key={c.chain_id} value={c.chain_id}>
                      {c.name}
                      {c.rpc_configured ? "" : " — RPC not configured"}
                    </option>
                  ))}
                </select>
              </Field>
              {chain && !chain.rpc_configured ? (
                <Notice tone="warn">
                  {chain.name} has no RPC configured on this server, so scans will be rejected. The server operator
                  must set this chain&apos;s RPC URL in the backend environment (see .env.example).
                </Notice>
              ) : null}

              <Field id={fid("addr")} label="Hook address" hint="Format: 0x followed by 40 hex characters" error={err.hook_address?.message}>
                <input
                  id={fid("addr")}
                  className={`${inputClass} font-mono`}
                  placeholder="0x…"
                  autoComplete="off"
                  spellCheck={false}
                  required
                  aria-invalid={err.hook_address ? true : undefined}
                  aria-describedby={describedBy("addr")}
                  {...form.register("hook_address")}
                />
              </Field>
              <PermissionPreview address={address.trim()} />

              <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
                <Field id={fid("pool")} label="Pool ID (optional)" hint="Analyse one specific pool" error={err.pool_id?.message}>
                  <input
                    id={fid("pool")}
                    className={`${inputClass} font-mono`}
                    placeholder="0x… (32 bytes)"
                    autoComplete="off"
                    spellCheck={false}
                    aria-invalid={err.pool_id ? true : undefined}
                    aria-describedby={describedBy("pool")}
                    {...form.register("pool_id")}
                  />
                </Field>
                <Field id={fid("block")} label="Block (optional)" hint="Defaults to the latest block" error={err.block_number?.message}>
                  <input
                    id={fid("block")}
                    className={inputClass}
                    inputMode="numeric"
                    placeholder="latest"
                    autoComplete="off"
                    aria-invalid={err.block_number ? true : undefined}
                    aria-describedby={describedBy("block")}
                    {...form.register("block_number")}
                  />
                </Field>
              </div>

              <label className="flex items-start gap-2.5 text-sm">
                <input type="checkbox" className="mt-0.5 size-4 accent-[var(--color-accent)]" {...form.register("discover_pools")} />
                <span>
                  Discover pools
                  <span className="block text-xs text-faint">Search PoolManager Initialize events for pools that use this hook.</span>
                </span>
              </label>

              {create.isError ? <ErrorState error={create.error} title="Scan was not started" /> : null}

              <div>
                <Button type="submit" variant="primary" loading={create.isPending} disabled={!!jobId && !stream.done}>
                  Start scan <ArrowRight aria-hidden="true" className="size-4" />
                </Button>
              </div>
            </form>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Progress" description={scanId ? undefined : "Stages"} />
          <CardBody>
            {jobId ? (
              <div className="flex flex-col gap-4">
                <JobProgress jobId={jobId} stream={stream} title="Scan" />
                {stream.done && scanId ? (
                  <Button asChild variant={stream.status === "succeeded" ? "primary" : "secondary"}>
                    <Link href={`/app/scans/${scanId}`}>
                      Open {stream.status === "succeeded" ? "results" : "partial results"} <ArrowRight aria-hidden="true" className="size-4" />
                    </Link>
                  </Button>
                ) : null}
              </div>
            ) : (
              <ol className="flex list-decimal flex-col gap-2 pl-5 text-sm text-muted">
                <li>Pin a block and read runtime code; detect proxies.</li>
                <li>Decode the 14 permission bits from the address.</li>
                <li>Fetch verified source (Etherscan) or match local artifacts (Anvil).</li>
                <li>Discover pools and read their state via extsload.</li>
                <li>Run analyzers; each finding links to its evidence.</li>
              </ol>
            )}
          </CardBody>
        </Card>
      </div>
    </>
  );
}

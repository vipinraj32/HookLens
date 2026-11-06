import {
  ArrowRight,
  Binary,
  Coins,
  FileCheck2,
  FlaskConical,
  Gauge,
  GitBranch,
  KeyRound,
  Layers,
  Lock,
  Network,
  Radio,
  ShieldAlert,
  Sparkles,
  Split,
} from "lucide-react";
import Link from "next/link";

import { FindingExplorer } from "@/components/landing/finding-explorer";
import { PermissionDecoder } from "@/components/landing/permission-decoder";
import { ProductTabs } from "@/components/landing/product-tabs";
import { Terminal } from "@/components/landing/terminal";

const REPO = "https://github.com/vipinraj32/HookLens";

const CHECKS = [
  {
    icon: Lock,
    code: "WDR",
    title: "Withdrawal blockers",
    body: "Reverts reachable from remove-liquidity callbacks: pauses, time locks, oracle checks.",
    detail: "Followed through internal and virtual calls, so logic behind a BaseHook dispatcher is found too.",
  },
  {
    icon: Radio,
    code: "ORC",
    title: "Oracle dependence",
    body: "Callbacks that read external price feeds, and whether the oracle address can be replaced.",
    detail: "Covers staleness and zero-price reverts, and oracles that a privileged role can swap.",
  },
  {
    icon: Coins,
    code: "FEE",
    title: "Dynamic fees",
    body: "Hooks that override the LP fee on each swap or update it.",
    detail: "Shows who controls the fee and the bounds the setters enforce.",
  },
  {
    icon: KeyRound,
    code: "ACC",
    title: "Admin powers",
    body: "Owner-only functions whose state changes what callbacks do. Also flags tx.origin authentication.",
    detail: "Includes pause switches and privileged configuration read inside swap and liquidity callbacks.",
  },
  {
    icon: Layers,
    code: "UPG",
    title: "Upgradeability",
    body: "Proxies, upgrade functions and initializers anyone can call.",
    detail: "On-chain it resolves EIP-1967, EIP-1167 and EIP-897 proxies; from source it detects delegating fallbacks.",
  },
  {
    icon: Network,
    code: "EXT",
    title: "External calls",
    body: "Callbacks that call other contracts during swaps or liquidity changes.",
    detail: "Each external call can fail or behave unexpectedly, and that can block the pool operation.",
  },
  {
    icon: Split,
    code: "ACT",
    title: "Custom accounting",
    body: "Return-delta permissions and callbacks that move currency through the PoolManager.",
    detail: "These are the hooks that can change what traders pay and what LPs receive.",
  },
  {
    icon: Binary,
    code: "PRM",
    title: "Permission integrity",
    body: "Address bits checked against getHookPermissions() and against the callbacks actually implemented.",
    detail: "Invalid sets, such as a return delta without its base callback, are reported.",
  },
];

const PIPELINE = [
  { icon: Binary, title: "Resolve & decode", body: "Pin a block, read code, detect proxies, and decode the permission bits." },
  { icon: ShieldAlert, title: "Deterministic analyzers", body: "Source-AST and bytecode rules. Every finding has a stable ID and evidence." },
  { icon: FlaskConical, title: "Fork simulations", body: "Foundry scenarios against the real PoolManager, with decoded traces." },
  { icon: Gauge, title: "LP exposure", body: "Exact v4 integer math. Every figure is tagged on-chain, measured or hypothetical." },
  { icon: Sparkles, title: "Grounded explanations", body: "Optional AI explanations, rejected if they cite evidence that doesn't exist." },
  { icon: FileCheck2, title: "Reports", body: "HTML, JSON, SARIF and PDF, all rendered from the same findings." },
];

const COMPARE: [string, string, string][] = [
  ["Input", "Solidity source (local or GitHub)", "A deployed hook address"],
  ["Needs", "Nothing: no keys, server or RPC", "HookLens server, forge, an RPC endpoint"],
  ["Tells you", "Which risky patterns the code contains, and where", "What actually happened on a fork at one block"],
  ["Result labels", "Static indicators (inferred)", "Passed, failed, reverted, unsupported (observed)"],
  ["Best for", "Pull requests, audit preparation, CI gates", "Due diligence before providing liquidity"],
];

function SectionHeading({ id, eyebrow, title, lead }: { id: string; eyebrow: string; title: string; lead?: string }) {
  return (
    <div className="max-w-2xl">
      <p className="font-mono text-xs uppercase tracking-widest text-accent">{eyebrow}</p>
      <h2 id={id} className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">
        {title}
      </h2>
      {lead ? <p className="mt-3 text-muted">{lead}</p> : null}
    </div>
  );
}

export default function Landing() {
  return (
    <div className="min-h-dvh">
      <header className="sticky top-0 z-20 border-b border-line/60 bg-bg/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-3.5">
          <Link href="/" className="flex items-center gap-2">
            <span aria-hidden="true" className="grid size-7 place-items-center rounded-md bg-accent/15 ring-1 ring-accent/40">
              <span className="size-2.5 rounded-full bg-accent" />
            </span>
            <span className="text-[15px] font-semibold tracking-tight">HookLens</span>
          </Link>
          <nav aria-label="Primary" className="flex items-center gap-1 text-sm">
            <span className="hidden items-center gap-1 md:flex">
              <a href="#offer" className="rounded-md px-3 py-2 text-muted hover:text-fg">
                Products
              </a>
              <a href="#try" className="rounded-md px-3 py-2 text-muted hover:text-fg">
                Try it
              </a>
              <a href="#checks" className="rounded-md px-3 py-2 text-muted hover:text-fg">
                Checks
              </a>
              <a href="#example" className="rounded-md px-3 py-2 text-muted hover:text-fg">
                Example
              </a>
            </span>
            <a href={REPO} className="rounded-md px-3 py-2 text-muted hover:text-fg">
              <GitBranch aria-hidden="true" className="mr-1.5 inline size-4" />
              Source
            </a>
            <Link href="/app" className="rounded-md bg-surface-2 px-3 py-2 text-fg ring-1 ring-line hover:bg-line/60">
              Open app
            </Link>
          </nav>
        </div>
      </header>

      <main>
        {/* ------------------------------------------------------------------ hero */}
        <section className="landing-glow">
          <div className="mx-auto grid max-w-6xl grid-cols-1 items-center gap-12 px-6 pb-20 pt-16 sm:pt-20 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
            <div>
              <p className="mb-5 inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1 text-xs text-muted">
                <span aria-hidden="true" className="size-1.5 rounded-full bg-ok" />
                Open source · Uniswap v4 hooks · Web app, CLI and GitHub Action
              </p>
              <h1 className="text-4xl font-semibold leading-[1.1] tracking-tight sm:text-5xl">
                See what your liquidity is <span className="text-accent">really</span> exposed to.
              </h1>
              <p className="mt-5 max-w-xl text-lg text-muted">
                HookLens reads a Uniswap v4 hook&apos;s code, runs it on a fork, and shows you, with evidence, when a
                withdrawal can be blocked, a fee raised or accounting changed.
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <Link
                  href="/app/scan"
                  className="inline-flex h-11 items-center gap-2 rounded-md bg-accent px-5 text-sm font-medium text-bg hover:bg-accent-strong"
                >
                  Scan a deployed hook <ArrowRight aria-hidden="true" className="size-4" />
                </Link>
                <a
                  href="#offer"
                  className="inline-flex h-11 items-center rounded-md border border-line bg-surface px-5 text-sm font-medium hover:bg-surface-2"
                >
                  Scan source in CI
                </a>
              </div>
              <dl className="mt-10 grid max-w-md grid-cols-3 gap-4 text-sm">
                <div>
                  <dt className="text-faint">Analyzers</dt>
                  <dd className="mt-1 text-xl font-semibold">10</dd>
                </div>
                <div>
                  <dt className="text-faint">Fork scenarios</dt>
                  <dd className="mt-1 text-xl font-semibold">6</dd>
                </div>
                <div>
                  <dt className="text-faint">Report formats</dt>
                  <dd className="mt-1 text-xl font-semibold">5</dd>
                </div>
              </dl>
            </div>
            <Terminal />
          </div>
        </section>

        {/* ------------------------------------------------------------------ products */}
        <section id="offer" aria-labelledby="offer-h" className="scroll-mt-16 border-y border-line bg-surface/40">
          <div className="landing-reveal mx-auto max-w-6xl px-6 py-20">
            <SectionHeading
              id="offer-h"
              eyebrow="What we offer"
              title="One analysis engine, four ways to use it"
              lead="The web app, the CLI and the GitHub Action share the same analyzers, so a finding has the same ID wherever you see it."
            />
            <div className="mt-10">
              <ProductTabs />
            </div>
          </div>
        </section>

        {/* ------------------------------------------------------------------ decoder */}
        <section id="try" aria-labelledby="try-h" className="scroll-mt-16">
          <div className="landing-reveal mx-auto max-w-6xl px-6 py-20">
            <SectionHeading
              id="try-h"
              eyebrow="Try it now"
              title="Decode any hook address"
              lead="A v4 hook's address encodes which callbacks the PoolManager will call. Paste one and see which pool operations it can touch. Callbacks that affect withdrawals or settled amounts are highlighted."
            />
            <div className="mt-10">
              <PermissionDecoder />
            </div>
          </div>
        </section>

        {/* ------------------------------------------------------------------ checks */}
        <section id="checks" aria-labelledby="checks-h" className="scroll-mt-16 border-y border-line bg-surface/40">
          <div className="landing-reveal mx-auto max-w-6xl px-6 py-20">
            <SectionHeading
              id="checks-h"
              eyebrow="What it checks"
              title="Risks that matter to LPs"
              lead="Each rule is deterministic and has a stable ID. Click a card for details, or run hooklens rules for the full list."
            />
            <ul className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {CHECKS.map(({ icon: Icon, code, title, body, detail }) => (
                <li key={code}>
                  <details className="group h-full rounded-xl border border-line bg-bg transition-colors hover:border-accent/50 open:border-accent/60">
                    <summary className="flex h-full cursor-pointer list-none flex-col p-5 [&::-webkit-details-marker]:hidden">
                      <span className="flex items-center justify-between">
                        <span className="grid size-9 place-items-center rounded-md bg-surface-2 text-accent transition-transform group-hover:scale-105">
                          <Icon aria-hidden="true" className="size-4" />
                        </span>
                        <span className="font-mono text-[11px] text-faint">HL.{code}</span>
                      </span>
                      <span className="mt-4 text-sm font-semibold">{title}</span>
                      <span className="mt-2 text-sm leading-relaxed text-muted">{body}</span>
                      <span className="mt-3 text-xs text-accent group-open:hidden">More ›</span>
                    </summary>
                    <p className="border-t border-line px-5 py-4 text-xs leading-relaxed text-muted">{detail}</p>
                  </details>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* ------------------------------------------------------------------ example */}
        <section id="example" aria-labelledby="example-h" className="scroll-mt-16">
          <div className="landing-reveal mx-auto max-w-6xl px-6 py-20">
            <SectionHeading
              id="example-h"
              eyebrow="Example report"
              title="Explore a real scan"
              lead="These findings come from running the CLI on HookLens's own deliberately flawed test hooks. Filter, search, and expand a finding to see its LP impact and the source that triggered it."
            />
            <div className="mt-10">
              <FindingExplorer />
            </div>
          </div>
        </section>

        {/* ------------------------------------------------------------------ static vs execution */}
        <section aria-labelledby="modes-h" className="border-y border-line bg-surface/40">
          <div className="landing-reveal mx-auto max-w-6xl px-6 py-20">
            <SectionHeading
              id="modes-h"
              eyebrow="Two kinds of evidence"
              title="Static scan vs. execution test"
              lead="HookLens never mixes them. Every result says which kind it is."
            />
            <div className="mt-10 overflow-x-auto rounded-xl border border-line bg-bg">
              <table className="w-full min-w-[40rem] text-left text-sm">
                <thead className="border-b border-line text-xs uppercase tracking-wide text-faint">
                  <tr>
                    <th scope="col" className="px-5 py-3 font-medium">
                      <span className="sr-only">Aspect</span>
                    </th>
                    <th scope="col" className="px-5 py-3 font-medium">
                      Static scan <span className="normal-case text-faint">(CLI, Action, web)</span>
                    </th>
                    <th scope="col" className="px-5 py-3 font-medium">
                      Execution test <span className="normal-case text-faint">(lab, fork)</span>
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {COMPARE.map(([k, a, b]) => (
                    <tr key={k} className="hover:bg-surface/60">
                      <th scope="row" className="px-5 py-3 font-medium text-faint">
                        {k}
                      </th>
                      <td className="px-5 py-3">{a}</td>
                      <td className="px-5 py-3">{b}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        {/* ------------------------------------------------------------------ pipeline */}
        <section aria-labelledby="how" className="landing-reveal mx-auto max-w-6xl px-6 py-20">
          <SectionHeading id="how" eyebrow="How it works" title="From address to evidence" />
          <ol className="mt-10 grid gap-px overflow-hidden rounded-xl border border-line bg-line sm:grid-cols-2 lg:grid-cols-3">
            {PIPELINE.map(({ icon: Icon, title, body }, i) => (
              <li key={title} className="group bg-bg p-5 transition-colors hover:bg-surface">
                <div className="flex items-center gap-3">
                  <span className="grid size-8 place-items-center rounded-md bg-surface-2 text-accent transition-colors group-hover:bg-accent group-hover:text-bg">
                    <Icon aria-hidden="true" className="size-4" />
                  </span>
                  <span className="font-mono text-xs text-faint">0{i + 1}</span>
                </div>
                <h3 className="mt-4 text-sm font-semibold">{title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">{body}</p>
              </li>
            ))}
          </ol>
        </section>

        {/* ------------------------------------------------------------------ honesty */}
        <section aria-labelledby="honest" className="border-t border-line">
          <div className="landing-reveal mx-auto max-w-6xl px-6 py-20">
            <SectionHeading id="honest" eyebrow="Read this" title="What HookLens is not" />
            <ul className="mt-8 grid gap-4 text-sm text-muted sm:grid-cols-3">
              <li className="rounded-xl border border-line p-5">
                <strong className="mb-1.5 block text-fg">Not an audit.</strong>
                Findings are indicators for review, not confirmed exploits. A report with no findings does not mean a
                hook is safe.
              </li>
              <li className="rounded-xl border border-line p-5">
                <strong className="mb-1.5 block text-fg">Not a forecast.</strong>
                Fee income is unavailable unless measured. Price scenarios are explicitly hypothetical.
              </li>
              <li className="rounded-xl border border-line p-5">
                <strong className="mb-1.5 block text-fg">No keys, no signing.</strong>
                Analysis never needs a wallet. Privileged actions are impersonated inside a local fork only.
              </li>
            </ul>
            <div className="mt-12 flex flex-wrap items-center justify-between gap-4 rounded-xl border border-accent/30 bg-accent/5 p-6">
              <p className="text-lg font-medium">Ready to look inside a hook?</p>
              <div className="flex flex-wrap gap-3">
                <Link
                  href="/app/scan"
                  className="inline-flex h-10 items-center gap-2 rounded-md bg-accent px-4 text-sm font-medium text-bg hover:bg-accent-strong"
                >
                  Scan a hook <ArrowRight aria-hidden="true" className="size-4" />
                </Link>
                <a
                  href={`${REPO}/blob/main/docs/cli.md`}
                  className="inline-flex h-10 items-center rounded-md border border-line bg-surface px-4 text-sm font-medium hover:bg-surface-2"
                >
                  Install the CLI
                </a>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-line px-6 py-6 text-center text-xs text-faint">
        HookLens · Open source · Results describe the exact configuration and block they were produced at.
      </footer>
    </div>
  );
}

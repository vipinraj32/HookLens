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
  Split,
} from "lucide-react";
import Link from "next/link";

import { HookLifecycle } from "@/components/landing/hook-lifecycle";
import { LiveStatus } from "@/components/landing/live-status";
import { PermissionDecoder } from "@/components/landing/permission-decoder";
import { ProductTabs } from "@/components/landing/product-tabs";

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

const FLOW = [
  { icon: Binary, title: "Hook Scanner", body: "Resolve a deployed hook, pin a block, decode its permission bits.", href: "/app/scan" },
  { icon: ShieldAlert, title: "Hook Intelligence", body: "Static findings with evidence: admin powers, oracles, fees, proxies.", href: "/app/scans" },
  { icon: FlaskConical, title: "Adversarial Lab", body: "Foundry scenarios against the real PoolManager on a fork.", href: "/app/lab" },
  { icon: Gauge, title: "LP Exposure", body: "Exact v4 math for your range, with measured lab effects.", href: "/app/lp" },
  { icon: FileCheck2, title: "Reports", body: "JSON and PDF built from the same findings and runs.", href: "/app/reports" },
] as const;

const WHY = [
  {
    title: "Why hooks matter",
    tone: "text-accent",
    points: [
      "A v4 pool's hook is fixed at creation and runs on every swap or liquidity change it enables.",
      "It can revert, override the LP fee, or move tokens through return deltas.",
      "Admin roles, oracles and proxies can change that behaviour after you deposit.",
    ],
  },
  {
    title: "What LPs should investigate",
    tone: "text-warn",
    points: [
      "Can anything make beforeRemoveLiquidity or afterRemoveLiquidity revert?",
      "Who can change the fee, and within which bounds?",
      "Does the hook take a delta from swaps or withdrawals?",
      "Can the code be upgraded, or the oracle replaced?",
    ],
  },
  {
    title: "How HookLens tests it",
    tone: "text-violet",
    points: [
      "Static analyzers on verified source and bytecode, each finding with evidence.",
      "Foundry scenarios on a fork at a pinned block: real reverts, deltas and traces.",
      "Exact v4 position math, with every figure tagged measured or hypothetical.",
    ],
  },
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
              <a href="#lifecycle" className="rounded-md px-3 py-2 text-muted hover:text-fg">
                How hooks work
              </a>
              <a href="#try" className="rounded-md px-3 py-2 text-muted hover:text-fg">
                Decode
              </a>
              <a href="#checks" className="rounded-md px-3 py-2 text-muted hover:text-fg">
                Checks
              </a>
              <a href="#offer" className="rounded-md px-3 py-2 text-muted hover:text-fg">
                Products
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
          <div className="mx-auto grid max-w-6xl grid-cols-1 items-center gap-12 px-6 pb-16 pt-16 sm:pt-20 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
            <div>
              <p className="mb-5 inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1 text-xs text-muted">
                <span aria-hidden="true" className="size-1.5 rounded-full bg-accent" />
                Uniswap v4 hook analysis · open source
              </p>
              <h1 className="text-4xl font-semibold leading-[1.08] tracking-tight sm:text-5xl">
                See what your liquidity is{" "}
                <span className="bg-gradient-to-r from-accent to-violet bg-clip-text text-transparent">really</span>{" "}
                exposed to
              </h1>
              <p className="mt-5 max-w-xl text-lg text-muted">
                Analyze Uniswap v4 hooks. Simulate real pool interactions. Understand LP exposure.
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <Link
                  href="/app/scan"
                  className="inline-flex h-11 items-center gap-2 rounded-xl bg-accent px-5 text-sm font-medium text-bg shadow-[0_0_24px_-6px_var(--color-accent)] hover:bg-accent-strong"
                >
                  Analyze a Hook <ArrowRight aria-hidden="true" className="size-4" />
                </Link>
                <a
                  href="#lifecycle"
                  className="inline-flex h-11 items-center rounded-xl border border-line bg-surface px-5 text-sm font-medium hover:border-violet/60 hover:bg-surface-2"
                >
                  Explore How Hooks Work
                </a>
              </div>
              <div className="mt-10 max-w-2xl">
                <LiveStatus />
              </div>
            </div>
            <ol aria-label="HookLens workflow" className="flex flex-col gap-2">
              {FLOW.map(({ icon: Icon, title, body, href }, i) => (
                <li key={title}>
                  <Link
                    href={href}
                    className="group flex items-start gap-4 rounded-2xl border border-line bg-surface/70 p-4 transition-colors hover:border-accent/50 hover:bg-surface-2"
                  >
                    <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-accent/10 text-accent ring-1 ring-accent/30 transition-colors group-hover:bg-accent group-hover:text-bg">
                      <Icon aria-hidden="true" className="size-4" />
                    </span>
                    <span className="min-w-0">
                      <span className="flex items-center gap-2 text-sm font-semibold">
                        <span className="font-mono text-[11px] text-faint">0{i + 1}</span>
                        {title}
                      </span>
                      <span className="mt-1 block text-sm text-muted">{body}</span>
                    </span>
                  </Link>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* ------------------------------------------------------------------ lifecycle */}
        <section id="lifecycle" aria-labelledby="lifecycle-h" className="scroll-mt-16 border-y border-line bg-surface/40">
          <div className="mx-auto max-w-6xl px-6 py-20">
            <SectionHeading
              id="lifecycle-h"
              eyebrow="How v4 hooks work"
              title="Follow a pool operation through its hook"
              lead="Pick an operation and step through it. Pink steps are hook callbacks: code the pool creator chose, running inside your swap or your withdrawal."
            />
            <div className="mt-10">
              <HookLifecycle />
            </div>
          </div>
        </section>

        {/* ------------------------------------------------------------------ why */}
        <section aria-labelledby="why-h" className="mx-auto max-w-6xl px-6 py-20">
          <SectionHeading id="why-h" eyebrow="Why it matters" title="Hooks run inside every LP's position" />
          <div className="mt-10 grid grid-cols-1 gap-4 md:grid-cols-3">
            {WHY.map(({ title, points, tone }) => (
              <div key={title} className="rounded-2xl border border-line bg-surface/60 p-5">
                <h3 className={`text-sm font-semibold ${tone}`}>{title}</h3>
                <ul className="mt-3 flex flex-col gap-2 text-sm text-muted">
                  {points.map((p) => (
                    <li key={p} className="flex gap-2">
                      <span aria-hidden="true" className="mt-2 size-1 shrink-0 rounded-full bg-current" />
                      <span>{p}</span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
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

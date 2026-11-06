import {
  ArrowRight,
  Binary,
  Coins,
  FileCheck2,
  FileSearch,
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

import { BrandHomeLink, BrandLogo, BrandMark } from "@/components/brand";
import { HeroPipeline } from "@/components/landing/hero-pipeline";
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

const WORKFLOW = [
  { icon: Binary, title: "Hook address", body: "Paste a deployed v4 hook. HookLens pins a block and decodes its permission bits.", href: "/app/scan" },
  { icon: ShieldAlert, title: "Hook intelligence", body: "Static findings with evidence: admin powers, oracles, fees, deltas, proxies.", href: "/app/scans" },
  { icon: Network, title: "Pool resolution", body: "Pools that use the hook, found from PoolManager Initialize events or a given pool ID.", href: "/app/scans" },
  { icon: FlaskConical, title: "Adversarial lab", body: "Foundry scenarios against the real PoolManager on a fork at the pinned block.", href: "/app/lab" },
  { icon: FileSearch, title: "Execution evidence", body: "Steps, expected vs observed, decoded reverts, token deltas and call traces.", href: "/app/evidence" },
  { icon: Gauge, title: "LP exposure", body: "Exact v4 math for your range, with measured lab effects kept apart from hypotheticals.", href: "/app/lp" },
  { icon: FileCheck2, title: "Report", body: "JSON and PDF built from the same findings and runs, with a content hash.", href: "/app/reports" },
] as const;

const PILLARS = [
  {
    icon: FlaskConical,
    title: "Adversarial Lab",
    body: "Withdrawal failure, oracle failure, fee escalation, admin and upgrade, accounting invariants and ordering, executed with forge on a fork. Unsupported scenarios say so instead of passing.",
    href: "/app/lab",
    cta: "Open the lab",
  },
  {
    icon: FileSearch,
    title: "Execution evidence",
    body: "Every run keeps its pinned block and hash, harness version, per-step expectations, decoded reverts, raw and decimal token deltas, and a command to reproduce it.",
    href: "/app/evidence",
    cta: "Browse evidence",
  },
  {
    icon: Gauge,
    title: "LP exposure",
    body: "Model a position with exact v4 math. Figures are tagged measured, hypothetical or unavailable, and market moves are never called hook losses.",
    href: "/app/lp",
    cta: "Model a position",
  },
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
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-3">
          <BrandHomeLink height={26} className="-ml-1.5" />
          <nav aria-label="Primary" className="flex items-center gap-1 text-sm">
            <span className="hidden items-center gap-1 md:flex">
              <a href="#how" className="rounded-md px-3 py-2 text-muted hover:text-fg">
                How it works
              </a>
              <a href="#lifecycle" className="rounded-md px-3 py-2 text-muted hover:text-fg">
                v4 hooks
              </a>
              <a href="#try" className="rounded-md px-3 py-2 text-muted hover:text-fg">
                Decode
              </a>
              <a href="#checks" className="rounded-md px-3 py-2 text-muted hover:text-fg">
                Checks
              </a>
            </span>
            <a href={REPO} className="hidden rounded-md px-3 py-2 text-muted hover:text-fg sm:inline-flex sm:items-center">
              <GitBranch aria-hidden="true" className="mr-1.5 inline size-4" />
              Source
            </a>
            <Link
              href="/app/scan"
              className="inline-flex h-9 items-center gap-1.5 rounded-full bg-accent px-4 font-medium text-bg hover:bg-accent-strong"
            >
              Launch app <ArrowRight aria-hidden="true" className="size-3.5" />
            </Link>
          </nav>
        </div>
      </header>

      <main>
        {/* ------------------------------------------------------------------ hero */}
        <section className="landing-glow">
          <div className="mx-auto grid max-w-6xl grid-cols-1 items-center gap-12 px-6 pb-20 pt-16 sm:pt-24 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
            <div>
              <p className="mb-6 inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1 text-xs text-muted">
                <BrandMark size={14} decorative />
                LP intelligence &amp; security testing for Uniswap v4
              </p>
              <h1 className="text-4xl font-semibold leading-[1.05] tracking-tight sm:text-5xl lg:text-[3.5rem]">
                Know what your liquidity is <span className="text-accent">exposed&nbsp;to.</span>
              </h1>
              <p className="mt-6 max-w-xl text-lg leading-relaxed text-muted">
                HookLens analyzes Uniswap v4 hooks, runs adversarial scenarios on forked chains, and turns the execution
                evidence into liquidity-provider intelligence you can inspect and reproduce.
              </p>
              <div className="mt-9 flex flex-wrap gap-3">
                <Link
                  href="/app/scan"
                  className="inline-flex h-12 items-center gap-2 rounded-full bg-accent px-6 text-sm font-semibold text-bg shadow-[0_10px_40px_-12px_rgb(255_0_153/0.7)] transition-colors hover:bg-accent-strong"
                >
                  Analyze a Hook <ArrowRight aria-hidden="true" className="size-4" />
                </Link>
                <a
                  href="#how"
                  className="inline-flex h-12 items-center rounded-full border border-line bg-surface px-6 text-sm font-medium transition-colors hover:border-line-strong hover:bg-surface-2"
                >
                  Explore How It Works
                </a>
              </div>
              <div className="mt-10 max-w-2xl">
                <LiveStatus />
              </div>
            </div>
            <HeroPipeline />
          </div>
        </section>

        {/* ------------------------------------------------------------------ how it works */}
        <section id="how" aria-labelledby="how-h" className="scroll-mt-16 border-y border-line bg-surface/40">
          <div className="mx-auto max-w-6xl px-6 py-20">
            <SectionHeading
              id="how-h"
              eyebrow="How it works"
              title="From a hook address to an LP-level answer"
              lead="Seven stages, each backed by data the server actually produced. In the app, every scan shows where it is in this flow."
            />
            <ol className="mt-10 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
              {WORKFLOW.map(({ icon: Icon, title, body, href }, i) => (
                <li key={title} className="landing-reveal">
                  <Link
                    href={href}
                    className="group flex h-full flex-col rounded-2xl border border-line bg-bg/60 p-4 transition-colors hover:border-accent/50 hover:bg-surface-2"
                  >
                    <span className="flex items-center justify-between">
                      <span className="grid size-9 place-items-center rounded-xl bg-accent/10 text-accent ring-1 ring-accent/30 transition-colors group-hover:bg-accent group-hover:text-bg">
                        <Icon aria-hidden="true" className="size-4" />
                      </span>
                      <span className="font-mono text-[11px] text-faint">0{i + 1}</span>
                    </span>
                    <span className="mt-3 text-sm font-semibold">{title}</span>
                    <span className="mt-1.5 text-xs leading-relaxed text-muted">{body}</span>
                  </Link>
                </li>
              ))}
            </ol>

            <div className="mt-14 grid grid-cols-1 gap-4 lg:grid-cols-3">
              {PILLARS.map(({ icon: Icon, title, body, href, cta }) => (
                <div key={title} className="landing-reveal flex flex-col rounded-2xl border border-accent/25 bg-gradient-to-b from-accent/[0.07] to-transparent p-6">
                  <Icon aria-hidden="true" className="size-5 text-accent" />
                  <h3 className="mt-4 text-lg font-semibold tracking-tight">{title}</h3>
                  <p className="mt-2 flex-1 text-sm leading-relaxed text-muted">{body}</p>
                  <Link href={href} className="mt-5 inline-flex items-center gap-1.5 text-sm font-medium text-accent hover:underline">
                    {cta} <ArrowRight aria-hidden="true" className="size-3.5" />
                  </Link>
                </div>
              ))}
            </div>
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

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-6 py-8 text-xs text-faint sm:flex-row">
          <BrandLogo height={20} />
          <p className="text-center sm:text-right">
            Open source · Not an audit · Results describe the exact configuration and block they were produced at.
          </p>
        </div>
      </footer>
    </div>
  );
}

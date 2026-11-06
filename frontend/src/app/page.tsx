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

import { BrandHomeLink, BrandLogo } from "@/components/brand";
import { HeroPipeline } from "@/components/landing/hero-pipeline";
import { HookLifecycle } from "@/components/landing/hook-lifecycle";
import { LiveStatus } from "@/components/landing/live-status";
import { PermissionDecoder } from "@/components/landing/permission-decoder";

const REPO = "https://github.com/vipinraj32/HookLens";

const WORKFLOW = [
  { icon: Binary, title: "Hook address", href: "/app/scan" },
  { icon: ShieldAlert, title: "Intelligence", href: "/app/scans" },
  { icon: Network, title: "Pools", href: "/app/scans" },
  { icon: FlaskConical, title: "Adversarial lab", href: "/app/lab" },
  { icon: FileSearch, title: "Evidence", href: "/app/evidence" },
  { icon: Gauge, title: "LP exposure", href: "/app/lp" },
  { icon: FileCheck2, title: "Report", href: "/app/reports" },
] as const;

const FEATURES = [
  { icon: FlaskConical, title: "Adversarial Lab", body: "Six Foundry scenarios on a forked chain.", href: "/app/lab" },
  { icon: FileSearch, title: "Execution evidence", body: "Steps, reverts, token deltas, traces, repro.", href: "/app/evidence" },
  { icon: Gauge, title: "LP exposure", body: "Exact v4 math, measured vs hypothetical.", href: "/app/lp" },
] as const;

const CHECKS = [
  { icon: Lock, code: "WDR", title: "Withdrawal blockers", detail: "Reverts reachable from remove-liquidity callbacks: pauses, time locks, oracle checks." },
  { icon: Radio, code: "ORC", title: "Oracle dependence", detail: "Price feeds read in callbacks, staleness and zero-price reverts, replaceable oracles." },
  { icon: Coins, code: "FEE", title: "Dynamic fees", detail: "LP fee overrides and updates, who controls them and the bounds enforced." },
  { icon: KeyRound, code: "ACC", title: "Admin powers", detail: "Owner-only state that changes callback behaviour, pause switches, tx.origin auth." },
  { icon: Layers, code: "UPG", title: "Upgradeability", detail: "EIP-1967, EIP-1167 and EIP-897 proxies, upgrade functions, open initializers." },
  { icon: Network, code: "EXT", title: "External calls", detail: "Calls to other contracts during swaps or liquidity changes that can fail the operation." },
  { icon: Split, code: "ACT", title: "Custom accounting", detail: "Return-delta permissions and callbacks that move currency through the PoolManager." },
  { icon: Binary, code: "PRM", title: "Permission integrity", detail: "Address bits vs getHookPermissions() vs implemented callbacks; invalid sets." },
];

function Heading({ id, eyebrow, title }: { id: string; eyebrow: string; title: string }) {
  return (
    <div>
      <p className="font-mono text-[11px] uppercase tracking-widest text-accent">{eyebrow}</p>
      <h2 id={id} className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">
        {title}
      </h2>
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
              <a href="#checks" className="rounded-md px-3 py-2 text-muted hover:text-fg">
                Checks
              </a>
            </span>
            <a href={REPO} aria-label="Source on GitHub" className="hidden rounded-md p-2 text-muted hover:text-fg sm:inline-flex">
              <GitBranch aria-hidden="true" className="size-4" />
            </a>
            <Link href="/app" className="inline-flex h-9 items-center rounded-full border border-line px-4 font-medium hover:border-line-strong hover:bg-surface-2">
              Open app
            </Link>
          </nav>
        </div>
      </header>

      <main>
        {/* hero */}
        <section className="landing-glow">
          <div className="mx-auto grid max-w-6xl grid-cols-1 items-center gap-12 px-6 pb-16 pt-16 sm:pt-20 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <div>
              <h1 className="text-4xl font-semibold leading-[1.05] tracking-tight sm:text-5xl lg:text-[3.5rem]">
                Know what your liquidity is <span className="text-accent">exposed&nbsp;to.</span>
              </h1>
              <p className="mt-5 max-w-lg text-lg text-muted">
                Analyze Uniswap v4 hooks, test them on a fork, and see what it means for your position.
              </p>
              <div className="mt-8 flex flex-wrap items-center gap-3">
                <Link
                  href="/app/scan"
                  className="inline-flex h-12 items-center gap-2 rounded-full bg-accent px-6 text-sm font-semibold text-bg shadow-[0_10px_40px_-12px_rgb(255_0_153/0.7)] transition-colors hover:bg-accent-strong"
                >
                  Analyze a Hook <ArrowRight aria-hidden="true" className="size-4" />
                </Link>
                <a href="#how" className="inline-flex h-12 items-center px-3 text-sm font-medium text-muted hover:text-fg">
                  How it works
                </a>
              </div>
              <div className="mt-10">
                <LiveStatus />
              </div>
            </div>
            <HeroPipeline />
          </div>
        </section>

        {/* how it works */}
        <section id="how" aria-labelledby="how-h" className="scroll-mt-16 border-y border-line bg-surface/40">
          <div className="mx-auto max-w-6xl px-6 py-16">
            <Heading id="how-h" eyebrow="How it works" title="Address in, LP exposure out" />
            <ol className="mt-8 flex flex-wrap items-center gap-2">
              {WORKFLOW.map(({ icon: Icon, title, href }, i) => (
                <li key={title} className="flex items-center gap-2">
                  {i > 0 ? <span aria-hidden="true" className="h-px w-4 bg-line-strong sm:w-6" /> : null}
                  <Link
                    href={href}
                    className="group inline-flex items-center gap-2 rounded-full border border-line bg-bg/60 py-1.5 pl-1.5 pr-3.5 text-sm transition-colors hover:border-accent/60 hover:bg-surface-2"
                  >
                    <span className="grid size-7 place-items-center rounded-full bg-accent/10 text-accent transition-colors group-hover:bg-accent group-hover:text-bg">
                      <Icon aria-hidden="true" className="size-3.5" />
                    </span>
                    {title}
                  </Link>
                </li>
              ))}
            </ol>
            <ul className="mt-10 grid grid-cols-1 gap-3 md:grid-cols-3">
              {FEATURES.map(({ icon: Icon, title, body, href }) => (
                <li key={title}>
                  <Link
                    href={href}
                    className="group flex h-full items-start gap-4 rounded-2xl border border-accent/20 bg-gradient-to-b from-accent/[0.07] to-transparent p-5 transition-colors hover:border-accent/50"
                  >
                    <Icon aria-hidden="true" className="mt-0.5 size-5 shrink-0 text-accent" />
                    <span className="min-w-0 flex-1">
                      <span className="block font-semibold">{title}</span>
                      <span className="mt-1 block text-sm text-muted">{body}</span>
                    </span>
                    <ArrowRight aria-hidden="true" className="mt-1 size-4 shrink-0 text-faint transition-transform group-hover:translate-x-0.5 group-hover:text-accent" />
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        </section>

        {/* lifecycle */}
        <section id="lifecycle" aria-labelledby="lifecycle-h" className="scroll-mt-16">
          <div className="mx-auto max-w-6xl px-6 py-16">
            <Heading id="lifecycle-h" eyebrow="v4 hooks" title="Where a hook runs in your swap or withdrawal" />
            <div className="mt-8">
              <HookLifecycle />
            </div>
          </div>
        </section>

        {/* decoder */}
        <section id="try" aria-labelledby="try-h" className="scroll-mt-16 border-y border-line bg-surface/40">
          <div className="landing-reveal mx-auto max-w-6xl px-6 py-16">
            <Heading id="try-h" eyebrow="Try it" title="Decode any hook address" />
            <div className="mt-8">
              <PermissionDecoder />
            </div>
          </div>
        </section>

        {/* checks */}
        <section id="checks" aria-labelledby="checks-h" className="scroll-mt-16">
          <div className="landing-reveal mx-auto max-w-6xl px-6 py-16">
            <Heading id="checks-h" eyebrow="Checks" title="What HookLens looks for" />
            <ul className="mt-8 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {CHECKS.map(({ icon: Icon, code, title, detail }) => (
                <li key={code}>
                  <details className="group h-full rounded-xl border border-line bg-surface/60 transition-colors hover:border-accent/50 open:border-accent/60">
                    <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-3 [&::-webkit-details-marker]:hidden">
                      <Icon aria-hidden="true" className="size-4 shrink-0 text-accent" />
                      <span className="flex-1 text-sm font-medium">{title}</span>
                      <span className="font-mono text-[10px] text-faint">HL.{code}</span>
                    </summary>
                    <p className="border-t border-line px-4 py-3 text-xs leading-relaxed text-muted">{detail}</p>
                  </details>
                </li>
              ))}
            </ul>
          </div>
        </section>
      </main>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-4 px-6 py-8 text-xs text-faint sm:flex-row">
          <BrandLogo height={20} />
          <p className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1">
            <span>Not an audit. Findings are indicators for review.</span>
            <a href={`${REPO}/blob/main/docs/cli.md`} className="hover:text-fg">
              CLI &amp; GitHub Action
            </a>
            <a href={REPO} className="hover:text-fg">
              Source
            </a>
          </p>
        </div>
      </footer>
    </div>
  );
}

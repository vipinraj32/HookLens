import {
  ArrowRight,
  Binary,
  FileCheck2,
  FlaskConical,
  Gauge,
  GitBranch,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import Link from "next/link";

const PIPELINE = [
  {
    icon: Binary,
    title: "Resolve & decode",
    body: "Pins a block, reads runtime code, detects proxies (EIP-1967, EIP-1167, EIP-897), and decodes the 14 permission bits from the hook address against the vendored v4-core Hooks.sol.",
  },
  {
    icon: ShieldAlert,
    title: "Deterministic analyzers",
    body: "Source-AST and bytecode analyzers for access control, dynamic fees, oracles, external calls, withdrawals, return deltas and upgradeability. Every finding has a stable ID and links to evidence.",
  },
  {
    icon: FlaskConical,
    title: "Fork simulations",
    body: "Runs Foundry scenarios against the real PoolManager on a fork: withdrawal under oracle failure, pause or upgrade, fee escalation, accounting invariants and ordering. Results are real forge outcomes with decoded traces.",
  },
  {
    icon: Gauge,
    title: "LP exposure",
    body: "Exact integer ports of TickMath, SqrtPriceMath and LiquidityAmounts. Each figure is tagged on-chain, measured, hypothetical or unavailable — never blended.",
  },
  {
    icon: Sparkles,
    title: "Grounded explanations",
    body: "Optional AI explanations are validated against the evidence: unknown evidence IDs, out-of-range source lines, invented numbers and severity changes are rejected.",
  },
  {
    icon: FileCheck2,
    title: "Reports",
    body: "Versioned JSON with a content hash, plus PDF. Includes provenance, reproduction commands, assumptions and limitations.",
  },
];

export default function Landing() {
  return (
    <div className="min-h-dvh">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <Link href="/" className="flex items-center gap-2">
          <span aria-hidden="true" className="grid size-7 place-items-center rounded-md bg-accent/15 ring-1 ring-accent/40">
            <span className="size-2.5 rounded-full bg-accent" />
          </span>
          <span className="text-[15px] font-semibold tracking-tight">HookLens</span>
        </Link>
        <nav aria-label="Primary" className="flex items-center gap-1 text-sm">
          <a href="https://github.com/vipinraj32/HookLens" className="rounded-md px-3 py-2 text-muted hover:text-fg">
            <GitBranch aria-hidden="true" className="mr-1.5 inline size-4" />
            Source
          </a>
          <Link href="/app" className="rounded-md bg-surface-2 px-3 py-2 text-fg ring-1 ring-line hover:bg-line/60">
            Open app
          </Link>
        </nav>
      </header>

      <main>
        <section className="mx-auto max-w-6xl px-6 pb-20 pt-16 sm:pt-24">
          <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-line bg-surface px-3 py-1 text-xs text-muted">
            Open source · Uniswap v4 hooks
          </p>
          <h1 className="max-w-3xl text-4xl font-semibold leading-tight tracking-tight sm:text-5xl">
            See what your liquidity is <span className="text-accent">really</span> exposed to.
          </h1>
          <p className="mt-5 max-w-2xl text-lg text-muted">
            HookLens inspects a Uniswap v4 hook, runs adversarial fork simulations against it, and shows an LP — with
            evidence — when a withdrawal can be blocked, a fee can be raised, or accounting can drift.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link
              href="/app/scan"
              className="inline-flex h-11 items-center gap-2 rounded-md bg-accent px-5 text-sm font-medium text-bg hover:bg-accent-strong"
            >
              Scan a hook <ArrowRight aria-hidden="true" className="size-4" />
            </Link>
            <Link
              href="/app"
              className="inline-flex h-11 items-center rounded-md border border-line bg-surface px-5 text-sm font-medium hover:bg-surface-2"
            >
              Dashboard
            </Link>
          </div>
        </section>

        <section aria-labelledby="how" className="border-y border-line bg-surface/50">
          <div className="mx-auto max-w-6xl px-6 py-16">
            <h2 id="how" className="text-xl font-semibold tracking-tight">
              How it works
            </h2>
            <ol className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {PIPELINE.map(({ icon: Icon, title, body }, i) => (
                <li key={title} className="rounded-xl border border-line bg-bg p-5">
                  <div className="flex items-center gap-3">
                    <span className="grid size-8 place-items-center rounded-md bg-surface-2 text-accent">
                      <Icon aria-hidden="true" className="size-4" />
                    </span>
                    <span className="font-mono text-xs text-faint">0{i + 1}</span>
                  </div>
                  <h3 className="mt-4 text-sm font-semibold">{title}</h3>
                  <p className="mt-2 text-sm leading-relaxed text-muted">{body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        <section aria-labelledby="honest" className="mx-auto max-w-6xl px-6 py-16">
          <h2 id="honest" className="text-xl font-semibold tracking-tight">
            What HookLens is not
          </h2>
          <ul className="mt-6 grid gap-4 text-sm text-muted sm:grid-cols-3">
            <li className="rounded-xl border border-line p-5">
              <strong className="block text-fg">Not an audit.</strong>
              Static findings are labelled <em>inferred</em>; only fork-reproduced behaviour is labelled{" "}
              <em>observed</em>. Absence of findings does not mean a hook is safe.
            </li>
            <li className="rounded-xl border border-line p-5">
              <strong className="block text-fg">Not a forecast.</strong>
              Fee income is reported as unavailable unless measured. Price scenarios are explicitly hypothetical.
            </li>
            <li className="rounded-xl border border-line p-5">
              <strong className="block text-fg">No keys, no signing.</strong>
              Analysis never needs a wallet. Privileged actions are impersonated inside a local fork only.
            </li>
          </ul>
        </section>
      </main>

      <footer className="border-t border-line px-6 py-6 text-center text-xs text-faint">
        HookLens · Open source · Results describe the exact configuration and block they were produced at.
      </footer>
    </div>
  );
}

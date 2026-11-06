"use client";

import { ArrowRight, Check, FlaskConical, Globe, SquareTerminal, Workflow } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Tab, TabPanel, Tabs, TabsList } from "@/components/tabs";
import { CodeBlock } from "@/components/ui";

const REPO = "https://github.com/vipinraj32/HookLens";

type Product = {
  id: string;
  icon: typeof Globe;
  label: string;
  title: string;
  lead: string;
  points: string[];
  code: string;
  cta: ReactNode;
};

const PRODUCTS: Product[] = [
  {
    id: "web",
    icon: Globe,
    label: "Web app",
    title: "Analyse a deployed hook",
    lead: "Paste a hook address on Ethereum, Sepolia or a local Anvil chain. HookLens pins a block and follows the evidence end to end.",
    points: [
      "Decodes permission bits and compares them with the code",
      "Detects proxies and fetches verified source",
      "Discovers pools that use the hook",
      "Runs fork simulations against the real PoolManager",
      "Models LP positions with exact v4 math",
      "Grounded AI explanations, plus JSON and PDF reports",
    ],
    code: "1. Open the scanner\n2. Choose a chain and paste the hook address\n3. Review findings and evidence, then run the Adversarial lab",
    cta: (
      <Link
        href="/app/scan"
        className="inline-flex h-10 items-center gap-2 rounded-md bg-accent px-4 text-sm font-medium text-bg hover:bg-accent-strong"
      >
        Scan a hook <ArrowRight aria-hidden="true" className="size-4" />
      </Link>
    ),
  },
  {
    id: "cli",
    icon: SquareTerminal,
    label: "CLI",
    title: "Scan Solidity source locally",
    lead: "The same analysis engine as a command-line tool. It runs on a local project or a public GitHub repo, with no API key, database or server.",
    points: [
      "Detects hooks with a confidence level; skips mocks, tests and interfaces",
      "Standalone offline HTML report with filters and source navigation",
      "Versioned JSON and SARIF for GitHub Code Scanning",
      "Remote repos are cloned into a temp directory and never executed",
      "Separate exit codes for findings (1) and scanner errors (2–5)",
    ],
    code: [
      'pip install "hooklens @ git+https://github.com/vipinraj32/HookLens#subdirectory=packages/hooklens"',
      "",
      "hooklens scan ./my-hook-project --local --html report.html",
      "hooklens scan https://github.com/uniswapfoundation/v4-template --html report.html",
      "hooklens scan . --json report.json --sarif report.sarif --fail-on high",
    ].join("\n"),
    cta: (
      <a href={`${REPO}/blob/main/docs/cli.md`} className="inline-flex items-center gap-1.5 text-sm font-medium text-accent hover:underline">
        CLI documentation <ArrowRight aria-hidden="true" className="size-4" />
      </a>
    ),
  },
  {
    id: "action",
    icon: Workflow,
    label: "GitHub Action",
    title: "Gate every pull request",
    lead: "A composite action that runs the real CLI in your workflow, so new hook code is reviewed before it merges.",
    points: [
      "Writes a job summary",
      "Shows findings in Security → Code scanning",
      "Uploads the reports as an artifact",
      "Can keep one PR comment updated on every run",
      "Fork-safe: privileged steps are skipped on fork PRs, and no secrets are needed",
    ],
    code: [
      "permissions:",
      "  contents: read",
      "  security-events: write",
      "jobs:",
      "  hooklens:",
      "    runs-on: ubuntu-latest",
      "    steps:",
      "      - uses: actions/checkout@v4",
      "        with: { submodules: recursive }",
      "      - uses: vipinraj32/HookLens@main",
      "        with:",
      "          fail-on: high",
    ].join("\n"),
    cta: (
      <a
        href={`${REPO}/blob/main/examples/github-actions/hooklens.yml`}
        className="inline-flex items-center gap-1.5 text-sm font-medium text-accent hover:underline"
      >
        Example workflow <ArrowRight aria-hidden="true" className="size-4" />
      </a>
    ),
  },
  {
    id: "lab",
    icon: FlaskConical,
    label: "Execution lab",
    title: "Execute, don't just read",
    lead: "Foundry scenarios run against a deployed hook on a forked chain. The outcomes are real forge results with decoded traces.",
    points: [
      "Withdrawal under oracle failure, pause or upgrade",
      "Fee escalation, including unauthorized fee changes",
      "Accounting invariants and transaction ordering",
      "Each scenario reports passed, failed, expected revert or unsupported, for one fork and block",
      "Includes a reproduction command for every run",
    ],
    code: "hooklens lab --chain 31337 --hook 0x8c555A02175966f3c564bF3f3d62E722E6D04200 --json lab.json",
    cta: (
      <Link href="/app/scan" className="inline-flex items-center gap-1.5 text-sm font-medium text-accent hover:underline">
        Open the lab in the app <ArrowRight aria-hidden="true" className="size-4" />
      </Link>
    ),
  },
];

export function ProductTabs() {
  return (
    <Tabs defaultValue="web">
      <TabsList aria-label="HookLens products">
        {PRODUCTS.map(({ id, icon: Icon, label }) => (
          <Tab key={id} value={id} className="inline-flex items-center gap-2">
            <Icon aria-hidden="true" className="size-4" />
            {label}
          </Tab>
        ))}
      </TabsList>
      {PRODUCTS.map((p) => (
        <TabPanel key={p.id} value={p.id} className="landing-fade">
          <div className="grid grid-cols-1 gap-8 lg:grid-cols-2">
            <div>
              <h3 className="text-lg font-semibold tracking-tight">{p.title}</h3>
              <p className="mt-2 text-muted">{p.lead}</p>
              <ul className="mt-5 flex flex-col gap-2.5 text-sm">
                {p.points.map((pt) => (
                  <li key={pt} className="flex items-start gap-2.5">
                    <Check aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-ok" />
                    <span>{pt}</span>
                  </li>
                ))}
              </ul>
              <div className="mt-6">{p.cta}</div>
            </div>
            <CodeBlock code={p.code} className="min-w-0 self-start" copy={p.id !== "web"} />
          </div>
        </TabPanel>
      ))}
    </Tabs>
  );
}

"use client";

import {
  Activity,
  BookOpen,
  ChevronRight,
  FileSearch,
  FileText,
  FlaskConical,
  Gauge,
  LayoutDashboard,
  Menu,
  ScanSearch,
  ShieldAlert,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, type ReactNode } from "react";

import { BrandHomeLink } from "@/components/brand";
import { useChains, useWorkerHealth } from "@/lib/api/hooks";
import { cn } from "@/lib/format";
import { useNetwork } from "@/lib/network";

const DOCS = "https://github.com/vipinraj32/HookLens/tree/main/docs";

type NavItem = { href: string; label: string; icon: typeof LayoutDashboard; match: (p: string) => boolean };

/** Grouped by the HookLens workflow: analyze a hook, test it on a fork, then report. */
const NAV_GROUPS: { label: string; items: NavItem[] }[] = [
  {
    label: "Analyze",
    items: [
      { href: "/app", label: "Overview", icon: LayoutDashboard, match: (p) => p === "/app" },
      { href: "/app/scan", label: "Hook Scanner", icon: ScanSearch, match: (p) => p === "/app/scan" },
      {
        href: "/app/scans",
        label: "Hook Intelligence",
        icon: ShieldAlert,
        match: (p) => p === "/app/scans" || (p.startsWith("/app/scans/") && !p.endsWith("/lab")),
      },
    ],
  },
  {
    label: "Test & measure",
    items: [
      {
        href: "/app/lab",
        label: "Adversarial Lab",
        icon: FlaskConical,
        match: (p) => p === "/app/lab" || /^\/app\/scans\/[^/]+\/lab$/.test(p),
      },
      { href: "/app/evidence", label: "Evidence", icon: FileSearch, match: (p) => p.startsWith("/app/evidence") },
      { href: "/app/lp", label: "LP Exposure", icon: Gauge, match: (p) => p.startsWith("/app/lp") },
    ],
  },
  {
    label: "Report",
    items: [{ href: "/app/reports", label: "Reports", icon: FileText, match: (p) => p.startsWith("/app/reports") }],
  },
];
const NAV = NAV_GROUPS.flatMap((g) => g.items);

function DocsLink() {
  return (
    <li className="mt-2 border-t border-line pt-2">
      <a
        href={DOCS}
        target="_blank"
        rel="noreferrer"
        className="flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-muted hover:bg-surface-2 hover:text-fg"
      >
        <BookOpen aria-hidden="true" className="size-4" />
        Documentation
        <span className="sr-only">(opens GitHub)</span>
      </a>
    </li>
  );
}

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <div className="flex flex-col gap-4">
      {NAV_GROUPS.map((g) => (
        <div key={g.label}>
          <p className="mb-1 px-2.5 text-[11px] font-medium uppercase tracking-wider text-faint">{g.label}</p>
          <ul className="flex flex-col gap-0.5">
            {g.items.map(({ href, label, icon: Icon, match }) => {
              const active = match(pathname);
              return (
                <li key={href}>
                  <Link
                    href={href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "relative flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-muted transition-colors hover:bg-surface-2 hover:text-fg",
                      active &&
                        "bg-accent/10 text-fg before:absolute before:inset-y-1.5 before:left-0 before:w-0.5 before:rounded-full before:bg-accent",
                    )}
                  >
                    <Icon aria-hidden="true" className={cn("size-4", active && "text-accent")} />
                    {label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
      <ul>
        <DocsLink />
      </ul>
    </div>
  );
}

function NavFallback() {
  return (
    <ul className="flex flex-col gap-0.5">
      {NAV.map(({ href, label, icon: Icon }) => (
        <li key={href}>
          <Link href={href} className="flex items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm text-muted hover:bg-surface-2">
            <Icon aria-hidden="true" className="size-4" />
            {label}
          </Link>
        </li>
      ))}
      <DocsLink />
    </ul>
  );
}

function Dot({ ok, warn }: { ok: boolean; warn?: boolean }) {
  return <span aria-hidden="true" className={cn("inline-block size-1.5 rounded-full", ok ? "bg-ok" : warn ? "bg-warn" : "bg-bad")} />;
}

function SystemStatus() {
  const { data, isError } = useWorkerHealth();
  if (isError) {
    return (
      <p className="flex items-center gap-2 text-xs text-bad">
        <Dot ok={false} /> API unreachable
      </p>
    );
  }
  if (!data) return <p className="text-xs text-faint">Checking backend…</p>;
  return (
    <ul className="flex flex-col gap-1.5 text-xs text-muted">
      <li className="flex items-center gap-2">
        <Dot ok={data.dispatcher.ok} /> Jobs: {data.dispatcher.backend}
      </li>
      <li className="flex items-center gap-2">
        <Dot ok={data.forge.available} /> Foundry {data.forge.available ? "available" : "unavailable"}
      </li>
      <li className="flex items-center gap-2">
        <Dot ok={data.ai.enabled} warn={!data.ai.enabled} /> AI {data.ai.enabled ? "enabled" : "not configured"}
      </li>
    </ul>
  );
}

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  return (
    <div className="flex h-full flex-col gap-6 px-3 py-4">
      <BrandHomeLink height={24} className="self-start" />
      <nav aria-label="Main">
        <Suspense fallback={<NavFallback />}>
          <NavLinks onNavigate={onNavigate} />
        </Suspense>
      </nav>
      <div className="mt-auto rounded-xl border border-line bg-bg/60 p-3">
        <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-fg">
          <Activity aria-hidden="true" className="size-3.5 text-accent" /> System
        </p>
        <SystemStatus />
      </div>
    </div>
  );
}

const CRUMB: Record<string, string> = {
  scan: "Hook Scanner",
  scans: "Hook Intelligence",
  lab: "Adversarial Lab",
  lp: "LP Exposure",
  reports: "Reports",
  evidence: "Evidence",
};

function Breadcrumbs() {
  const pathname = usePathname();
  const parts = pathname.split("/").filter(Boolean).slice(1); // drop "app"
  const crumbs: { href: string; label: string }[] = [{ href: "/app", label: "Overview" }];
  let href = "/app";
  parts.forEach((seg, i) => {
    href += `/${seg}`;
    const prev = parts[i - 1];
    if (prev === "scans") crumbs.push({ href, label: `Scan ${seg.slice(0, 8)}` });
    else if (prev === "reports") crumbs.push({ href, label: `Report ${seg.slice(0, 8)}` });
    else if (CRUMB[seg]) crumbs.push({ href, label: CRUMB[seg] });
  });
  return (
    <nav aria-label="Breadcrumb" className="min-w-0">
      <ol className="flex min-w-0 items-center gap-1 text-sm">
        {crumbs.map((c, i) => {
          const last = i === crumbs.length - 1;
          return (
            <li key={c.href} className="flex min-w-0 items-center gap-1">
              {i > 0 ? <ChevronRight aria-hidden="true" className="size-3.5 shrink-0 text-faint" /> : null}
              {last ? (
                <span aria-current="page" className="truncate text-fg">
                  {c.label}
                </span>
              ) : (
                <Link href={c.href} className="truncate text-muted hover:text-fg">
                  {c.label}
                </Link>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

/** Preferred network: filters lists and pre-selects the scanner. It never changes server RPC config. */
function NetworkSelect() {
  const chains = useChains();
  const [network, setNetwork] = useNetwork();
  const current = chains.data?.find((c) => c.chain_id === network);
  return (
    <label className="flex items-center gap-2 text-xs text-muted">
      <span className="sr-only sm:not-sr-only">Network</span>
      <span className="relative">
        <span
          aria-hidden="true"
          className={cn(
            "pointer-events-none absolute left-2.5 top-1/2 size-1.5 -translate-y-1/2 rounded-full",
            current ? (current.rpc_configured ? "bg-ok" : "bg-warn") : "bg-violet",
          )}
        />
        <select
          value={network ?? ""}
          onChange={(e) => setNetwork(e.target.value ? Number(e.target.value) : null)}
          disabled={!chains.data}
          className="h-9 max-w-[9.5rem] rounded-lg border border-line bg-surface pl-6 pr-2 text-sm text-fg hover:border-violet/60 sm:max-w-none"
        >
          <option value="">All networks</option>
          {chains.data?.map((c) => (
            <option key={c.chain_id} value={c.chain_id}>
              {c.name}
              {c.rpc_configured ? "" : " (no RPC)"}
            </option>
          ))}
        </select>
      </span>
    </label>
  );
}

/**
 * Mobile navigation drawer: a manual popover in the top layer whose open/closed state is a
 * horizontal scroll-snap position, so swipe-to-dismiss is native scrolling. An
 * IntersectionObserver on the sheet is the single source of truth for open/closed.
 */
function MobileDrawer({ mainId }: { mainId: string }) {
  const drawerRef = useRef<HTMLDivElement>(null);
  const scrollerRef = useRef<HTMLDivElement>(null);
  const sheetRef = useRef<HTMLElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);

  const close = useCallback(() => {
    const scroller = scrollerRef.current;
    if (!scroller || !drawerRef.current?.matches(":popover-open")) return;
    scroller.scrollTo({ left: scroller.offsetWidth, behavior: "auto" });
  }, []);

  const open = useCallback(async () => {
    const drawer = drawerRef.current;
    const scroller = scrollerRef.current;
    if (!drawer || !scroller) return;
    drawer.showPopover();
    if (!CSS.supports("scroll-initial-target", "nearest")) {
      scroller.scrollTo({ left: scroller.offsetWidth, behavior: "instant" });
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    }
    scroller.scrollTo({ left: 0, behavior: "auto" });
  }, []);

  useEffect(() => {
    const drawer = drawerRef.current;
    const scroller = scrollerRef.current;
    const sheet = sheetRef.current;
    if (!drawer || !scroller || !sheet) return;
    const main = document.getElementById(mainId);
    const threshold = 1 / window.innerWidth;
    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries.at(-1);
        if (!entry) return;
        if (entry.intersectionRatio < threshold && drawer.matches(":popover-open")) {
          drawer.hidePopover();
          if (main) main.inert = false;
          btnRef.current?.setAttribute("aria-expanded", "false");
        }
        if (entry.intersectionRatio === 1) {
          if (main) main.inert = true;
          btnRef.current?.setAttribute("aria-expanded", "true");
          sheet.focus();
        }
      },
      { root: drawer, threshold: [threshold, 1] },
    );
    observer.observe(sheet);

    let onScroll: (() => void) | undefined;
    if (!CSS.supports("animation-timeline: scroll()")) {
      onScroll = () => {
        const ratio = 1 - scroller.scrollLeft / sheet.offsetWidth;
        drawer.style.setProperty("--drawer-backdrop", String(Math.max(0, Math.min(1, ratio))));
      };
      scroller.addEventListener("scroll", onScroll);
    }
    const onClick = (e: MouseEvent) => {
      if (!sheet.contains(e.target as Node)) close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    drawer.addEventListener("click", onClick);
    document.addEventListener("keydown", onKey);
    return () => {
      observer.disconnect();
      if (onScroll) scroller.removeEventListener("scroll", onScroll);
      drawer.removeEventListener("click", onClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [close, mainId]);

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        onClick={open}
        aria-label="Open navigation"
        aria-expanded="false"
        aria-controls="nav-drawer"
        className="inline-flex size-9 items-center justify-center rounded-md text-muted hover:bg-surface-2 hover:text-fg lg:hidden"
      >
        <Menu aria-hidden="true" className="size-5" />
      </button>
      <div ref={drawerRef} id="nav-drawer" className="Drawer" popover="manual">
        <div ref={scrollerRef} className="Drawer-scroller">
          <nav ref={sheetRef} tabIndex={-1} aria-label="Mobile" className="Drawer-sheet border-r border-line bg-surface outline-none">
            <div className="flex justify-end px-3 pt-3">
              <button
                type="button"
                onClick={close}
                aria-label="Close navigation"
                className="inline-flex size-8 items-center justify-center rounded-md text-muted hover:bg-surface-2"
              >
                <X aria-hidden="true" className="size-4" />
              </button>
            </div>
            <SidebarContent onNavigate={close} />
          </nav>
        </div>
      </div>
    </>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const mainId = "app-main";
  return (
    <div className="flex min-h-dvh">
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 overflow-y-auto border-r border-line bg-surface lg:block">
        <SidebarContent />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex h-14 items-center gap-3 border-b border-line bg-bg/85 px-4 backdrop-blur lg:px-8">
          <MobileDrawer mainId={mainId} />
          <span className="lg:hidden">
            <BrandHomeLink height={22} />
          </span>
          <span className="hidden min-w-0 flex-1 lg:block">
            <Suspense fallback={null}>
              <Breadcrumbs />
            </Suspense>
          </span>
          <span className="ml-auto">
            <NetworkSelect />
          </span>
        </header>
        <div className="border-b border-line px-4 py-2 lg:hidden">
          <Suspense fallback={null}>
            <Breadcrumbs />
          </Suspense>
        </div>
        <main id={mainId} className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">{children}</main>
        <footer className="border-t border-line px-6 py-4 text-xs text-faint">
          HookLens presents deterministic analysis and fork-simulation results. It is not a security audit and does not
          establish that a hook is safe.
        </footer>
      </div>
    </div>
  );
}

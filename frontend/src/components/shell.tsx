"use client";

import { Activity, FileSearch, Gauge, LayoutDashboard, Menu, ScanSearch, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, type ReactNode } from "react";

import { useWorkerHealth } from "@/lib/api/hooks";
import { cn } from "@/lib/format";

const NAV = [
  { href: "/app", label: "Dashboard", icon: LayoutDashboard, exact: true },
  { href: "/app/scan", label: "New scan", icon: ScanSearch },
  { href: "/app/lp", label: "LP exposure", icon: Gauge },
  { href: "/app/evidence", label: "Evidence explorer", icon: FileSearch },
];

function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2 px-2 text-fg">
      <span aria-hidden="true" className="grid size-7 place-items-center rounded-md bg-accent/15 ring-1 ring-accent/40">
        <span className="size-2.5 rounded-full bg-accent" />
      </span>
      <span className="text-[15px] font-semibold tracking-tight">HookLens</span>
    </Link>
  );
}

function NavLinks({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <ul className="flex flex-col gap-0.5">
      {NAV.map(({ href, label, icon: Icon, exact }) => {
        const active = exact ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);
        return (
          <li key={href}>
            <Link
              href={href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-muted hover:bg-surface-2 hover:text-fg",
                active && "bg-surface-2 text-fg",
              )}
            >
              <Icon aria-hidden="true" className={cn("size-4", active && "text-accent")} />
              {label}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

function NavFallback() {
  return (
    <ul className="flex flex-col gap-0.5">
      {NAV.map(({ href, label, icon: Icon }) => (
        <li key={href}>
          <Link href={href} className="flex items-center gap-2.5 rounded-md px-2.5 py-2 text-sm text-muted hover:bg-surface-2">
            <Icon aria-hidden="true" className="size-4" />
            {label}
          </Link>
        </li>
      ))}
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
      <Logo />
      <nav aria-label="Main">
        <Suspense fallback={<NavFallback />}>
          <NavLinks onNavigate={onNavigate} />
        </Suspense>
      </nav>
      <div className="mt-auto rounded-lg border border-line bg-bg/60 p-3">
        <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-fg">
          <Activity aria-hidden="true" className="size-3.5 text-accent" /> System
        </p>
        <SystemStatus />
      </div>
    </div>
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
      <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 border-r border-line bg-surface lg:block">
        <SidebarContent />
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 flex h-14 items-center gap-3 border-b border-line bg-bg/85 px-4 backdrop-blur lg:hidden">
          <MobileDrawer mainId={mainId} />
          <Logo />
        </header>
        <main id={mainId} className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 lg:px-8 lg:py-8">{children}</main>
        <footer className="border-t border-line px-6 py-4 text-xs text-faint">
          HookLens presents deterministic analysis and fork-simulation results. It is not a security audit and does not
          establish that a hook is safe.
        </footer>
      </div>
    </div>
  );
}

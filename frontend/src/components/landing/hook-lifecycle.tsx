"use client";

import { ChevronLeft, ChevronRight, Info, Pause, Play, RotateCcw } from "lucide-react";
import { useCallback, useEffect, useId, useMemo, useState, useSyncExternalStore, type KeyboardEvent } from "react";

import { cn } from "@/lib/format";

/*
 * Educational diagram of the Uniswap v4 call flow (v4-core PoolManager + Hooks library).
 * It is ILLUSTRATIVE: no transaction, chain or hook is read here. Every label describes how
 * v4 works in general; nothing on this component is data about a specific hook.
 */

type Lane = "router" | "pm" | "hook";
type Kind = "call" | "callback" | "internal" | "return";

type Step = {
  from: Lane;
  to: Lane;
  kind: Kind;
  label: string;
  title: string;
  body: string;
  /** Permission flag the PoolManager checks before making this call (hook calls only). */
  flag?: string;
  /** What an LP should investigate at this step. */
  lp?: string;
};

type View = {
  id: string;
  label: string;
  router: { name: string; sub: string };
  intro: string;
  steps: Step[];
};

const UNLOCK: Step[] = [
  {
    from: "router",
    to: "pm",
    kind: "call",
    label: "unlock(data)",
    title: "Open a flash-accounting session",
    body: "Every swap or liquidity change happens inside PoolManager.unlock. Balances are tracked as deltas and only settled at the end.",
  },
  {
    from: "pm",
    to: "router",
    kind: "callback",
    label: "unlockCallback(data)",
    title: "The router gets control back",
    body: "The PoolManager calls back into the router, which now performs the actual pool operations.",
  },
];

const VIEWS: View[] = [
  {
    id: "swap",
    label: "Swap",
    router: { name: "SwapRouter", sub: "trader's entry point" },
    intro: "A trader swaps through a router. The PoolManager calls the hook before and after the price moves.",
    steps: [
      ...UNLOCK,
      {
        from: "router",
        to: "pm",
        kind: "call",
        label: "swap(key, params, hookData)",
        title: "Request the swap",
        body: "The router asks the PoolManager to swap in the pool identified by the PoolKey, which names the hook contract.",
      },
      {
        from: "pm",
        to: "hook",
        kind: "callback",
        label: "beforeSwap()",
        flag: "beforeSwap",
        title: "beforeSwap: the hook runs first",
        body: "Called only if the hook address has the beforeSwap bit. The hook can revert the swap, return an LP fee override on dynamic-fee pools, or take part of the swap with beforeSwapReturnDelta.",
        lp: "Who can change the fee this returns, and within what bounds?",
      },
      {
        from: "pm",
        to: "pm",
        kind: "internal",
        label: "Pool.swap: price moves",
        title: "Swap math across ticks",
        body: "The pool walks ticks with concentrated-liquidity math. LP fees accrue to positions whose range contains the price.",
      },
      {
        from: "pm",
        to: "hook",
        kind: "callback",
        label: "afterSwap()",
        flag: "afterSwap",
        title: "afterSwap: the hook sees the result",
        body: "Called only with the afterSwap bit. With afterSwapReturnDelta, the hook can take or add tokens to the unspecified side of the swap.",
        lp: "Does the hook take a cut of trades, and can that cut change?",
      },
      {
        from: "router",
        to: "pm",
        kind: "call",
        label: "settle() / take()",
        title: "Pay in, take out",
        body: "The router pays the input currency and takes the output. Every delta, including the hook's, must net to zero.",
      },
      {
        from: "pm",
        to: "router",
        kind: "return",
        label: "unlock returns",
        title: "Session closes",
        body: "If any delta is still non-zero, unlock reverts with CurrencyNotSettled and the whole transaction is undone.",
      },
    ],
  },
  {
    id: "add",
    label: "Add Liquidity",
    router: { name: "PositionManager", sub: "LP's entry point" },
    intro: "An LP deposits tokens into a price range. The hook can approve, reject or reprice the deposit.",
    steps: [
      ...UNLOCK,
      {
        from: "router",
        to: "pm",
        kind: "call",
        label: "modifyLiquidity(+L)",
        title: "Request a deposit",
        body: "A positive liquidityDelta over [tickLower, tickUpper) asks the pool to mint liquidity for this position.",
      },
      {
        from: "pm",
        to: "hook",
        kind: "callback",
        label: "beforeAddLiquidity()",
        flag: "beforeAddLiquidity",
        title: "beforeAddLiquidity: gatekeeper",
        body: "Called only with the beforeAddLiquidity bit. A revert here rejects the deposit, for example an allow-list or a pause.",
        lp: "Can an admin stop new deposits, and under which conditions?",
      },
      {
        from: "pm",
        to: "pm",
        kind: "internal",
        label: "update position & ticks",
        title: "Liquidity is added",
        body: "The PoolManager updates the position and tick state, and computes the token amounts the LP owes from the current price.",
      },
      {
        from: "pm",
        to: "hook",
        kind: "callback",
        label: "afterAddLiquidity()",
        flag: "afterAddLiquidity",
        title: "afterAddLiquidity: can reprice",
        body: "Called only with the afterAddLiquidity bit. With afterAddLiquidityReturnDelta, the hook can change what the LP actually pays.",
        lp: "Is the amount you pay the amount the v4 math says?",
      },
      {
        from: "router",
        to: "pm",
        kind: "call",
        label: "settle()",
        title: "LP pays the tokens",
        body: "The position manager settles the negative deltas by paying both currencies to the PoolManager.",
      },
      {
        from: "pm",
        to: "router",
        kind: "return",
        label: "unlock returns",
        title: "Deposit complete",
        body: "All deltas are settled. The LP now owns liquidity in the range.",
      },
    ],
  },
  {
    id: "remove",
    label: "Remove Liquidity",
    router: { name: "PositionManager", sub: "LP's entry point" },
    intro: "Withdrawal is where hooks matter most to LPs: a callback here can delay, block or charge an exit.",
    steps: [
      ...UNLOCK,
      {
        from: "router",
        to: "pm",
        kind: "call",
        label: "modifyLiquidity(−L)",
        title: "Request a withdrawal",
        body: "A negative liquidityDelta burns the position's liquidity and collects accrued fees.",
      },
      {
        from: "pm",
        to: "hook",
        kind: "callback",
        label: "beforeRemoveLiquidity()",
        flag: "beforeRemoveLiquidity",
        title: "beforeRemoveLiquidity: can block exits",
        body: "Called only with the beforeRemoveLiquidity bit. A revert here, from a pause, a time lock or a failing oracle read, means the LP cannot withdraw.",
        lp: "What makes this revert? Can an admin or an external contract trigger it?",
      },
      {
        from: "pm",
        to: "pm",
        kind: "internal",
        label: "burn liquidity, accrue fees",
        title: "Liquidity is removed",
        body: "The PoolManager computes the principal and fees owed to the LP as positive deltas.",
      },
      {
        from: "pm",
        to: "hook",
        kind: "callback",
        label: "afterRemoveLiquidity()",
        flag: "afterRemoveLiquidity",
        title: "afterRemoveLiquidity: can charge the exit",
        body: "Called only with the afterRemoveLiquidity bit. A revert also blocks the exit. With afterRemoveLiquidityReturnDelta the hook can change what the LP receives.",
        lp: "Is there a withdrawal fee, and who sets it?",
      },
      {
        from: "router",
        to: "pm",
        kind: "call",
        label: "take()",
        title: "LP receives the tokens",
        body: "The position manager takes the positive deltas: principal plus fees, adjusted by any hook delta.",
      },
      {
        from: "pm",
        to: "router",
        kind: "return",
        label: "unlock returns",
        title: "Withdrawal complete",
        body: "If any earlier step reverted, nothing happened and the liquidity is still in the pool.",
      },
    ],
  },
  {
    id: "init",
    label: "Initialize",
    router: { name: "Pool creator", sub: "any account" },
    intro: "A pool is created once, with its hook fixed forever in the PoolKey. Initialize needs no unlock.",
    steps: [
      {
        from: "router",
        to: "pm",
        kind: "call",
        label: "initialize(key, sqrtPriceX96)",
        title: "Create the pool",
        body: "The PoolKey fixes currency0, currency1, fee, tick spacing and the hook address. Pool ID = keccak256(PoolKey).",
      },
      {
        from: "pm",
        to: "pm",
        kind: "internal",
        label: "validate hook address bits",
        title: "Permissions come from the address",
        body: "The low 14 bits of the hook address are its permissions. Invalid sets, such as a return delta without its base callback, are rejected.",
        lp: "Decode the address bits below: they tell you which callbacks can ever run.",
      },
      {
        from: "pm",
        to: "hook",
        kind: "callback",
        label: "beforeInitialize()",
        flag: "beforeInitialize",
        title: "beforeInitialize",
        body: "Called only with the beforeInitialize bit. The hook can refuse pool creation, for example to allow only one pool.",
      },
      {
        from: "pm",
        to: "pm",
        kind: "internal",
        label: "set slot0: price & tick",
        title: "Pool state is written",
        body: "The starting price and tick are stored. The pool is now live and the hook can never be changed for it.",
      },
      {
        from: "pm",
        to: "hook",
        kind: "callback",
        label: "afterInitialize()",
        flag: "afterInitialize",
        title: "afterInitialize",
        body: "Called only with the afterInitialize bit. Often used to record the pool or set initial hook state.",
      },
      {
        from: "pm",
        to: "router",
        kind: "return",
        label: "emit Initialize",
        title: "Initialize event",
        body: "This event is what HookLens reads to discover every pool that uses a given hook.",
      },
    ],
  },
];

const NODES: Record<Lane, { name: string; sub: string; body: string }> = {
  router: {
    name: "Router",
    sub: "",
    body: "The contract a user calls. It opens a session on the PoolManager and settles balances at the end.",
  },
  pm: {
    name: "PoolManager",
    sub: "singleton, holds all pools",
    body: "One contract holds every v4 pool. It enforces flash accounting and decides which hook callbacks to call from the hook address bits.",
  },
  hook: {
    name: "Hook contract",
    sub: "fixed per pool in the PoolKey",
    body: "Arbitrary code chosen by the pool creator. It only runs at the callbacks its address enables, but there it can revert, change fees or move tokens.",
  },
};

const LANE_X: Record<Lane, number> = { router: 110, pm: 370, hook: 630 };
const W = 740;
const TOP = 104;
const ROW = 46;

function subscribeMotion(cb: () => void) {
  const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
}
function useReducedMotion() {
  return useSyncExternalStore(
    subscribeMotion,
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    () => true,
  );
}

function Arrow({ step, y, state, motion }: { step: Step; y: number; state: "past" | "active" | "future"; motion: boolean }) {
  const x1 = LANE_X[step.from];
  const x2 = LANE_X[step.to];
  const color =
    state === "active"
      ? step.to === "hook"
        ? "var(--color-accent)"
        : "var(--color-violet)"
      : state === "past"
        ? "var(--color-muted)"
        : "var(--color-line)";
  const dash = step.kind === "return" || state === "future" ? "5 5" : undefined;
  const width = state === "active" ? 2.5 : 1.5;

  if (step.from === step.to) {
    // Self call: a small loop to the right of the lifeline.
    const d = `M ${x1 + 6} ${y - 10} h 48 v 20 h -44`;
    return (
      <g>
        <path d={d} fill="none" stroke={color} strokeWidth={width} strokeDasharray={dash} markerEnd={`url(#hl-arrow-${state})`} />
        <text x={x1 + 62} y={y + 4} className="font-mono text-[12px]" fill={state === "future" ? "var(--color-faint)" : "var(--color-fg)"}>
          {step.label}
        </text>
        {state === "active" && motion ? (
          <circle r="4.5" fill={color}>
            <animateMotion dur="1.4s" repeatCount="indefinite" path={d} />
          </circle>
        ) : null}
      </g>
    );
  }

  const dir = x2 > x1 ? 1 : -1;
  const sx = x1 + dir * 6;
  const ex = x2 - dir * 8;
  const mid = (x1 + x2) / 2;
  return (
    <g>
      <line x1={sx} y1={y} x2={ex} y2={y} stroke={color} strokeWidth={width} strokeDasharray={dash} markerEnd={`url(#hl-arrow-${state})`} />
      <text
        x={mid}
        y={y - 8}
        textAnchor="middle"
        className="font-mono text-[12px]"
        fill={state === "future" ? "var(--color-faint)" : state === "active" ? "var(--color-fg)" : "var(--color-muted)"}
      >
        {step.label}
      </text>
      {state === "active" && motion ? (
        <circle cy={y} r="5" fill={color}>
          <animate attributeName="cx" from={sx} to={ex} dur="1.2s" repeatCount="indefinite" />
          <animate attributeName="opacity" values="0;1;1;0" dur="1.2s" repeatCount="indefinite" />
        </circle>
      ) : null}
    </g>
  );
}

export function HookLifecycle() {
  const uid = useId();
  const reduced = useReducedMotion();
  const [viewId, setViewId] = useState(VIEWS[0].id);
  const [stepIdx, setStepIdx] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [nodeFocus, setNodeFocus] = useState<Lane | null>(null);
  const [hovered, setHovered] = useState<number | null>(null);

  const view = VIEWS.find((v) => v.id === viewId) ?? VIEWS[0];
  const steps = view.steps;
  const step = steps[stepIdx];
  const last = steps.length - 1;
  const height = TOP + steps.length * ROW + 24;

  const go = useCallback(
    (i: number) => {
      setNodeFocus(null);
      setStepIdx(Math.max(0, Math.min(last, i)));
    },
    [last],
  );

  useEffect(() => {
    if (!playing) return;
    const t = window.setTimeout(() => {
      if (stepIdx >= last) setPlaying(false);
      else setStepIdx(stepIdx + 1);
    }, 2600);
    return () => window.clearTimeout(t);
  }, [playing, stepIdx, last]);

  const selectView = (id: string) => {
    setViewId(id);
    setStepIdx(0);
    setPlaying(false);
    setNodeFocus(null);
  };

  const onKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowRight") {
      e.preventDefault();
      go(stepIdx + 1);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      go(stepIdx - 1);
    }
  };

  const hookCalls = useMemo(() => steps.filter((s) => s.to === "hook").length, [steps]);
  const nodes: Record<Lane, { name: string; sub: string; body: string }> = {
    ...NODES,
    router: { ...NODES.router, name: view.router.name, sub: view.router.sub },
  };
  const activeLanes = new Set<Lane>([step.from, step.to]);
  const detailNode = nodeFocus ? nodes[nodeFocus] : null;
  const previewStep = hovered !== null && hovered !== stepIdx ? steps[hovered] : null;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div role="tablist" aria-label="Pool operation" className="flex flex-wrap gap-1 rounded-xl border border-line bg-surface p-1">
          {VIEWS.map((v) => (
            <button
              key={v.id}
              type="button"
              role="tab"
              id={`${uid}-tab-${v.id}`}
              aria-selected={v.id === viewId}
              aria-controls={`${uid}-panel`}
              onClick={() => selectView(v.id)}
              className={cn(
                "rounded-lg px-3.5 py-1.5 text-sm transition-colors",
                v.id === viewId ? "bg-accent/15 text-fg ring-1 ring-accent/50" : "text-muted hover:text-fg",
              )}
            >
              {v.label}
            </button>
          ))}
        </div>
        <p className="inline-flex items-center gap-1.5 rounded-full border border-violet/40 bg-violet/10 px-3 py-1 text-xs text-violet">
          <Info aria-hidden="true" className="size-3.5" />
          Illustrative flow, not a live transaction
        </p>
      </div>

      <div
        id={`${uid}-panel`}
        role="tabpanel"
        aria-labelledby={`${uid}-tab-${view.id}`}
        className="grid grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]"
      >
        <div className="min-w-0 self-start rounded-2xl border border-line bg-gradient-to-b from-surface to-bg p-3 sm:p-4">
          <p className="px-1 pb-2 text-sm text-muted">{view.intro}</p>
          <div className="overflow-x-auto">
            <svg
              viewBox={`0 0 ${W} ${height}`}
              className="h-auto w-full min-w-[34rem]"
              role="img"
              aria-label={`${view.label} call flow between ${view.router.name}, PoolManager and the hook contract. Step ${stepIdx + 1} of ${steps.length}: ${step.label}.`}
            >
              <defs>
                {(["past", "active", "future"] as const).map((st) => (
                  <marker key={st} id={`hl-arrow-${st}`} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                    <path
                      d="M0 0 L10 5 L0 10 z"
                      fill={st === "active" ? "var(--color-fg)" : st === "past" ? "var(--color-muted)" : "var(--color-line)"}
                    />
                  </marker>
                ))}
              </defs>

              {(Object.keys(LANE_X) as Lane[]).map((lane) => {
                const x = LANE_X[lane];
                const on = activeLanes.has(lane) || nodeFocus === lane;
                const isHook = lane === "hook";
                return (
                  <g key={lane}>
                    <line x1={x} y1={78} x2={x} y2={height - 12} stroke="var(--color-line)" strokeDasharray="2 6" />
                    <g
                      role="button"
                      tabIndex={0}
                      aria-label={`${nodes[lane].name}: ${nodes[lane].body}`}
                      aria-pressed={nodeFocus === lane}
                      className="cursor-pointer outline-none"
                      onClick={() => setNodeFocus(nodeFocus === lane ? null : lane)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          setNodeFocus(nodeFocus === lane ? null : lane);
                        }
                      }}
                    >
                      <title>{nodes[lane].body}</title>
                      <rect
                        x={x - 96}
                        y={14}
                        width={192}
                        height={60}
                        rx={14}
                        fill={on ? (isHook ? "color-mix(in oklch, var(--color-accent) 18%, var(--color-surface))" : "var(--color-surface-2)") : "var(--color-surface)"}
                        stroke={on ? (isHook ? "var(--color-accent)" : "var(--color-violet)") : "var(--color-line)"}
                        strokeWidth={on ? 2 : 1}
                        className="transition-all duration-300"
                      />
                      <text x={x} y={40} textAnchor="middle" className="text-[15px] font-semibold" fill="var(--color-fg)">
                        {nodes[lane].name}
                      </text>
                      <text x={x} y={59} textAnchor="middle" className="text-[11px]" fill="var(--color-faint)">
                        {nodes[lane].sub}
                      </text>
                    </g>
                  </g>
                );
              })}

              {steps.map((s, i) => {
                const y = TOP + i * ROW + ROW / 2;
                const state = i < stepIdx ? "past" : i === stepIdx ? "active" : "future";
                return (
                  <g
                    key={`${view.id}-${i}`}
                    className="cursor-pointer"
                    onClick={() => go(i)}
                    onMouseEnter={() => setHovered(i)}
                    onMouseLeave={() => setHovered(null)}
                  >
                    <title>{`${s.title}: ${s.body}`}</title>
                    <rect
                      x={8}
                      y={y - ROW / 2 + 3}
                      width={W - 16}
                      height={ROW - 6}
                      rx={10}
                      fill={i === stepIdx ? "color-mix(in oklch, var(--color-accent) 7%, transparent)" : hovered === i ? "color-mix(in oklch, var(--color-fg) 4%, transparent)" : "transparent"}
                    />
                    <text x={18} y={y + 4} className="font-mono text-[11px]" fill="var(--color-faint)">
                      {String(i + 1).padStart(2, "0")}
                    </text>
                    <Arrow step={s} y={y} state={state} motion={!reduced} />
                    {s.flag ? (
                      <g>
                        <rect
                          x={LANE_X.hook + 14}
                          y={y - 11}
                          width={92}
                          height={22}
                          rx={11}
                          fill={state === "active" ? "var(--color-accent)" : "transparent"}
                          stroke={state === "future" ? "var(--color-line)" : "var(--color-accent)"}
                        />
                        <text
                          x={LANE_X.hook + 60}
                          y={y + 4}
                          textAnchor="middle"
                          className="text-[10.5px] font-medium"
                          fill={state === "active" ? "var(--color-bg)" : state === "future" ? "var(--color-faint)" : "var(--color-accent)"}
                        >
                          if bit set
                        </text>
                      </g>
                    ) : null}
                  </g>
                );
              })}
            </svg>
          </div>
        </div>

        <div className="flex min-w-0 flex-col gap-4" onKeyDown={onKey}>
          <div aria-live="polite" className="min-h-48 rounded-2xl border border-line bg-surface p-5">
            {detailNode ? (
              <>
                <p className="font-mono text-xs uppercase tracking-widest text-violet">Component</p>
                <h3 className="mt-2 text-lg font-semibold">{detailNode.name}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">{detailNode.body}</p>
                <button type="button" onClick={() => setNodeFocus(null)} className="mt-4 text-sm text-accent hover:underline">
                  Back to step {stepIdx + 1}
                </button>
              </>
            ) : (
              <>
                <p className="font-mono text-xs uppercase tracking-widest text-accent">
                  Step {stepIdx + 1} / {steps.length}
                  {step.flag ? <span className="ml-2 text-faint">· permission: {step.flag}</span> : null}
                </p>
                <h3 className="mt-2 text-lg font-semibold">{step.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-muted">{step.body}</p>
                {step.lp ? (
                  <p className="mt-4 rounded-lg border border-warn/30 bg-warn/5 px-3 py-2 text-sm">
                    <span className="font-medium text-warn">LP question: </span>
                    {step.lp}
                  </p>
                ) : null}
                {previewStep ? (
                  <p className="mt-3 text-xs text-faint">
                    Hovering step {hovered! + 1}: {previewStep.title}
                  </p>
                ) : null}
              </>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => go(stepIdx - 1)}
              disabled={stepIdx === 0}
              className="inline-flex h-10 items-center gap-1 rounded-lg border border-line bg-surface px-3 text-sm hover:bg-surface-2 disabled:opacity-40"
            >
              <ChevronLeft aria-hidden="true" className="size-4" /> Prev
            </button>
            {stepIdx < last ? (
              <button
                type="button"
                onClick={() => go(stepIdx + 1)}
                className="inline-flex h-10 items-center gap-1 rounded-lg bg-accent px-4 text-sm font-medium text-bg hover:bg-accent-strong"
              >
                Next <ChevronRight aria-hidden="true" className="size-4" />
              </button>
            ) : (
              <button
                type="button"
                onClick={() => go(0)}
                className="inline-flex h-10 items-center gap-1.5 rounded-lg bg-accent px-4 text-sm font-medium text-bg hover:bg-accent-strong"
              >
                <RotateCcw aria-hidden="true" className="size-4" /> Restart
              </button>
            )}
            <button
              type="button"
              onClick={() => {
                if (!playing && stepIdx >= last) setStepIdx(0);
                setPlaying(!playing);
              }}
              aria-pressed={playing}
              className="inline-flex h-10 items-center gap-1.5 rounded-lg border border-line px-3 text-sm text-muted hover:text-fg"
            >
              {playing ? <Pause aria-hidden="true" className="size-4" /> : <Play aria-hidden="true" className="size-4" />}
              {playing ? "Pause" : "Autoplay"}
            </button>
          </div>

          <ol aria-label={`${view.label} steps`} className="flex flex-col gap-1">
            {steps.map((s, i) => (
              <li key={i}>
                <button
                  type="button"
                  onClick={() => go(i)}
                  aria-current={i === stepIdx ? "step" : undefined}
                  className={cn(
                    "flex w-full items-center gap-3 rounded-lg px-3 py-1.5 text-left text-sm transition-colors",
                    i === stepIdx ? "bg-surface-2 text-fg" : "text-muted hover:bg-surface hover:text-fg",
                  )}
                >
                  <span
                    aria-hidden="true"
                    className={cn(
                      "size-2 shrink-0 rounded-full",
                      s.to === "hook" ? "bg-accent" : i <= stepIdx ? "bg-violet" : "bg-line",
                    )}
                  />
                  <span className="truncate font-mono text-[12.5px]">{s.label}</span>
                </button>
              </li>
            ))}
          </ol>
          <p className="text-xs text-faint">
            {hookCalls} of {steps.length} steps call the hook, and only if its address enables that callback. Use ← → to
            step.
          </p>
        </div>
      </div>
    </div>
  );
}

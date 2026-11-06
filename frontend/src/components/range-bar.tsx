import { TagBadge } from "@/components/ui";
import { cn } from "@/lib/format";

/**
 * Position range on a tick axis with the pool's current tick. Ticks are exact; the axis is
 * linear in ticks, which is logarithmic in price.
 */
export function RangeBar({
  tickLower,
  tickUpper,
  currentTick,
  lowerLabel,
  upperLabel,
  currentLabel,
}: {
  tickLower: number;
  tickUpper: number;
  currentTick: number | null | undefined;
  lowerLabel?: string;
  upperLabel?: string;
  currentLabel?: string;
}) {
  const ticks = [tickLower, tickUpper, ...(currentTick === null || currentTick === undefined ? [] : [currentTick])];
  const lo = Math.min(...ticks);
  const hi = Math.max(...ticks);
  const pad = Math.max(1, (hi - lo) * 0.15);
  const min = lo - pad;
  const max = hi + pad;
  const x = (t: number) => ((t - min) / (max - min)) * 100;
  const inRange = currentTick !== null && currentTick !== undefined && currentTick >= tickLower && currentTick < tickUpper;
  const state = currentTick === null || currentTick === undefined ? "unknown" : inRange ? "in range" : currentTick < tickLower ? "below range" : "above range";

  return (
    <figure className="rounded-xl border border-line bg-bg p-4">
      <figcaption className="mb-3 flex flex-wrap items-center gap-2 text-xs text-muted">
        <span className="font-medium text-fg">Position range</span>
        <span className={cn("rounded-full px-2 py-0.5", inRange ? "bg-ok/10 text-ok" : "bg-warn/10 text-warn")}>{state}</span>
        <span className="ml-auto flex items-center gap-1.5">
          range <TagBadge tag="hypothetical" /> current tick <TagBadge tag="on-chain" />
        </span>
      </figcaption>
      <svg viewBox="0 0 100 34" preserveAspectRatio="none" className="h-14 w-full" role="img"
        aria-label={`Range ticks ${tickLower} to ${tickUpper}; current tick ${currentTick ?? "unknown"} (${state}).`}>
        <line x1="0" y1="20" x2="100" y2="20" stroke="var(--color-line)" strokeWidth="0.6" vectorEffect="non-scaling-stroke" />
        <rect x={x(tickLower)} y="12" width={Math.max(0.4, x(tickUpper) - x(tickLower))} height="16" rx="1.5"
          fill="color-mix(in oklch, var(--color-accent) 22%, transparent)" stroke="var(--color-accent)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
        {currentTick !== null && currentTick !== undefined ? (
          <line x1={x(currentTick)} y1="4" x2={x(currentTick)} y2="32" stroke="var(--color-violet)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
        ) : null}
      </svg>
      <div className="relative mt-1 h-10 font-mono text-[11px] text-muted">
        <span className="absolute -translate-x-1/2 whitespace-nowrap text-center" style={{ left: `${x(tickLower)}%` }}>
          {tickLower}
          {lowerLabel ? <span className="block text-faint">{lowerLabel}</span> : null}
        </span>
        <span className="absolute -translate-x-1/2 whitespace-nowrap text-center" style={{ left: `${x(tickUpper)}%` }}>
          {tickUpper}
          {upperLabel ? <span className="block text-faint">{upperLabel}</span> : null}
        </span>
      </div>
      {currentTick !== null && currentTick !== undefined ? (
        <p className="mt-1 text-xs text-muted">
          <span aria-hidden="true" className="mr-1.5 inline-block h-3 w-0.5 bg-violet align-middle" />
          current tick <span className="font-mono text-fg">{currentTick}</span>
          {currentLabel ? <span className="text-faint"> · {currentLabel}</span> : null}
        </p>
      ) : null}
    </figure>
  );
}

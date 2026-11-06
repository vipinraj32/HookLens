import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function shortHex(value: string | null | undefined, head = 6, tail = 4): string {
  if (!value) return "—";
  if (value.length <= head + tail + 2) return value;
  return `${value.slice(0, head + 2)}…${value.slice(-tail)}`;
}

const dtf = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

/** Backend timestamps are UTC; some omit the trailing Z. */
export function parseUtc(ts: string): Date {
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(ts) ? ts : `${ts}Z`);
}

export function formatDate(ts: string | null | undefined): string {
  if (!ts) return "—";
  const d = parseUtc(ts);
  return Number.isNaN(d.getTime()) ? ts : dtf.format(d);
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

/** Group digits of a decimal string without converting through float. */
export function groupDecimal(value: string | number | null | undefined, maxFraction = 6): string {
  if (value === null || value === undefined || value === "") return "—";
  const s = String(value);
  const neg = s.startsWith("-");
  const [int, frac = ""] = (neg ? s.slice(1) : s).split(".");
  const grouped = int.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const f = frac.slice(0, maxFraction).replace(/0+$/, "");
  return `${neg ? "-" : ""}${grouped}${f ? `.${f}` : ""}`;
}

export function humanize(id: string): string {
  return id.replace(/[_-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function pct(v: number): string {
  return `${Math.round(v * 100)}%`;
}

/**
 * Exact decimal rendering of a signed integer token amount (no floating point), e.g.
 * formatUnits("-886113396", 6) === "-886.113396". Returns null when decimals are unknown.
 */
export function formatUnits(raw: string | null | undefined, decimals: number | null | undefined, maxFraction = 6): string | null {
  if (raw === null || raw === undefined || decimals === null || decimals === undefined || !/^-?\d+$/.test(raw)) return null;
  const neg = raw.startsWith("-");
  const digits = (neg ? raw.slice(1) : raw).replace(/^0+(?=\d)/, "");
  const padded = digits.padStart(decimals + 1, "0");
  const whole = padded.slice(0, padded.length - decimals) || "0";
  let frac = decimals ? padded.slice(padded.length - decimals) : "";
  const cut = frac.length > maxFraction && /[1-9]/.test(frac.slice(maxFraction));
  if (frac.length > maxFraction) frac = frac.slice(0, maxFraction);
  frac = frac.replace(/0+$/, "");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const isZero = /^0*$/.test(digits);
  if (cut && whole === "0" && !frac) return `${neg ? "-" : ""}<0.${"0".repeat(Math.max(0, maxFraction - 1))}1`;
  return `${neg && !isZero ? "-" : ""}${grouped}${frac ? `.${frac}` : ""}${cut ? "…" : ""}`;
}

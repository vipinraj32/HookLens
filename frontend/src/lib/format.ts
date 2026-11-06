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

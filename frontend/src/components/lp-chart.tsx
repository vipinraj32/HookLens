"use client";

import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { PriceScenario } from "@/lib/api/models";
import { groupDecimal } from "@/lib/format";

// Validated with the dataviz palette checker against the dark surface (#1e2129):
// CVD ΔE 26.8, normal-vision ΔE 31.8, both ≥ 3:1 contrast. Hold is also dashed so the
// two series never depend on colour alone.
const LP = "#3987e5";
const HOLD = "#d95926";

interface Point {
  move: number;
  label: string;
  lp: number;
  hold: number;
  lpText: string;
  holdText: string;
  range: string;
}

export function LpVsHoldChart({ data, unit }: { data: PriceScenario[]; unit: string }) {
  const points: Point[] = [...data]
    .sort((a, b) => a.price_move - b.price_move)
    .map((d) => ({
      move: d.price_move * 100,
      label: `${d.price_move > 0 ? "+" : ""}${Math.round(d.price_move * 100)}%`,
      lp: Number(d.lp_value_token1),
      hold: Number(d.hold_value_token1),
      lpText: d.lp_value_token1,
      holdText: d.hold_value_token1,
      range: d.range_state,
    }));
  if (points.length < 2) return null;
  return (
    <figure className="flex flex-col gap-2">
      <figcaption className="text-xs text-muted">
        Position value vs. holding the deposited tokens, in {unit}. Hypothetical instant price moves; no fees, no hook
        effects. Values are plotted as floats for display; the table holds the exact figures.
      </figcaption>
      <div className="h-72 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 8, right: 16, bottom: 4, left: 8 }}>
            <CartesianGrid stroke="var(--color-line)" strokeOpacity={0.5} vertical={false} />
            <XAxis
              dataKey="label"
              tick={{ fill: "var(--color-faint)", fontSize: 12 }}
              axisLine={{ stroke: "var(--color-line)" }}
              tickLine={false}
            />
            <YAxis
              tick={{ fill: "var(--color-faint)", fontSize: 12 }}
              axisLine={false}
              tickLine={false}
              width={72}
              tickFormatter={(v: number) => Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 2 }).format(v)}
            />
            <Tooltip
              cursor={{ stroke: "var(--color-muted)", strokeDasharray: "3 3" }}
              content={({ active, payload }) => {
                const p = active && payload?.[0] ? (payload[0].payload as Point) : null;
                if (!p) return null;
                return (
                  <div className="rounded-md border border-line bg-surface-2 px-3 py-2 text-xs shadow-lg">
                    <p className="mb-1 font-medium text-fg">
                      Price {p.label} · {p.range}
                    </p>
                    <p className="flex items-center gap-2 text-fg">
                      <span aria-hidden="true" className="inline-block h-0.5 w-3" style={{ background: LP }} /> LP{" "}
                      <span className="ml-auto font-mono">{groupDecimal(p.lpText)}</span>
                    </p>
                    <p className="flex items-center gap-2 text-fg">
                      <span aria-hidden="true" className="inline-block h-0.5 w-3 border-t-2 border-dashed" style={{ borderColor: HOLD }} /> Hold{" "}
                      <span className="ml-auto font-mono">{groupDecimal(p.holdText)}</span>
                    </p>
                  </div>
                );
              }}
            />
            <Legend wrapperStyle={{ fontSize: 12, color: "var(--color-muted)" }} />
            <Line type="monotone" dataKey="lp" name="LP position" stroke={LP} strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: "var(--color-surface)" }} activeDot={{ r: 5 }} isAnimationActive={false} />
            <Line type="monotone" dataKey="hold" name="Hold" stroke={HOLD} strokeWidth={2} strokeDasharray="6 4" dot={{ r: 4, strokeWidth: 2, stroke: "var(--color-surface)" }} activeDot={{ r: 5 }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

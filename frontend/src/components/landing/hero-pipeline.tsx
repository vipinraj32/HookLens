"use client";

import { Binary, FlaskConical, Gauge, ShieldAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/format";

/**
 * Illustrative HookLens pipeline for the hero. It explains what each stage produces and shows no
 * data: no addresses, hashes, scores or counts. It is labelled as illustrative.
 */
const STAGES = [
  {
    icon: Binary,
    title: "Hook address",
    lead: "Paste a deployed v4 hook.",
    produces: ["Block pinned", "Permission bits decoded", "Source or bytecode resolved"],
  },
  {
    icon: ShieldAlert,
    title: "Hook intelligence",
    lead: "Static analysis with evidence.",
    produces: ["Admin powers", "Oracle dependencies", "Dynamic fees", "Return deltas", "Upgradeability"],
  },
  {
    icon: FlaskConical,
    title: "Adversarial lab",
    lead: "Foundry scenarios on a fork.",
    produces: ["Withdrawal failure", "Oracle failure", "Fee escalation", "Admin & upgrade", "Accounting", "Ordering"],
  },
  {
    icon: Gauge,
    title: "LP exposure",
    lead: "What it means for a position.",
    produces: ["Exact v4 math", "Measured hook effects", "Hypothetical price moves"],
  },
] as const;

const STEP_MS = 3200;

export function HeroPipeline() {
  const [active, setActive] = useState(0);
  const [paused, setPaused] = useState(false);
  const [motion, setMotion] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: no-preference)");
    const sync = () => setMotion(mq.matches);
    sync();
    mq.addEventListener("change", sync);
    return () => mq.removeEventListener("change", sync);
  }, []);

  useEffect(() => {
    if (!motion || paused) return;
    const t = setInterval(() => setActive((i) => (i + 1) % STAGES.length), STEP_MS);
    return () => clearInterval(t);
  }, [motion, paused]);

  const stage = STAGES[active];
  return (
    <div
      ref={root}
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)}
      onBlur={(e) => {
        if (!root.current?.contains(e.relatedTarget as Node | null)) setPaused(false);
      }}
      className="hero-pipeline relative overflow-hidden rounded-3xl border border-line bg-surface/80 p-5 shadow-[0_30px_80px_-40px_rgb(0_0_0/0.6)] sm:p-6"
    >
      <div className="flex items-center justify-between gap-3">
        <p className="font-mono text-[11px] uppercase tracking-widest text-faint">HookLens pipeline</p>
        <p className="rounded-full border border-line px-2.5 py-0.5 text-[11px] text-faint">Illustrative flow · no live data</p>
      </div>

      <ol aria-label="Pipeline stages" className="relative mt-5 grid grid-cols-4 gap-2">
        <span aria-hidden="true" className="absolute left-[12.5%] right-[12.5%] top-5 h-px bg-line" />
        <span
          aria-hidden="true"
          className="pipeline-progress absolute left-[12.5%] top-5 h-px bg-accent"
          style={{ width: `${(active / (STAGES.length - 1)) * 75}%` }}
        />
        {STAGES.map((s, i) => {
          const Icon = s.icon;
          const on = i === active;
          const done = i < active;
          return (
            <li key={s.title} className="relative flex flex-col items-center text-center">
              <button
                type="button"
                onClick={() => setActive(i)}
                aria-pressed={on}
                aria-label={`${s.title}: ${s.lead}`}
                className={cn(
                  "relative grid size-10 place-items-center rounded-full border transition-all",
                  on
                    ? "scale-110 border-fg bg-fg text-bg shadow-[0_0_0_6px_rgb(244_241_246/0.08)]"
                    : done
                      ? "border-accent/60 bg-surface-2 text-accent"
                      : "border-line bg-surface-2 text-muted hover:border-line-strong hover:text-fg",
                )}
              >
                <Icon aria-hidden="true" className="size-4" />
              </button>
              <span className={cn("mt-2 text-[11px] font-medium leading-tight sm:text-xs", on ? "text-fg" : "text-faint")}>{s.title}</span>
            </li>
          );
        })}
      </ol>

      <div key={active} className="landing-fade mt-6 rounded-2xl border border-line bg-bg/70 p-4" data-state="active" aria-live="polite">
        <p className="text-sm font-semibold">
          <span className="font-mono text-xs text-accent">0{active + 1}</span> {stage.title}
          <span className="font-normal text-muted"> · {stage.lead}</span>
        </p>
        <ul aria-label="Produces" className="mt-3 flex flex-wrap gap-1.5">
          {stage.produces.map((p) => (
            <li key={p} className="rounded-full border border-accent/30 bg-accent/[0.07] px-2.5 py-0.5 text-[11px] text-fg">
              {p}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

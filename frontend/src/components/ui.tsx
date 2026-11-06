"use client";

import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { AlertTriangle, Check, Copy, Inbox, Loader2, RefreshCw } from "lucide-react";
import { forwardRef, useState, type ComponentProps, type ReactNode } from "react";

import { errorMessage, isApiError } from "@/lib/api/client";
import { cn } from "@/lib/format";

// ---------------------------------------------------------------- Button

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 rounded-lg text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 whitespace-nowrap",
  {
    variants: {
      variant: {
        primary: "bg-accent text-bg hover:bg-accent-strong",
        secondary: "border border-line bg-surface-2 text-fg hover:bg-line/60",
        ghost: "text-muted hover:bg-surface-2 hover:text-fg",
        danger: "border border-bad/50 text-bad hover:bg-bad/10",
      },
      size: {
        sm: "h-8 px-3",
        md: "h-10 px-4",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export interface ButtonProps extends ComponentProps<"button">, VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, asChild, loading, children, disabled, ...props },
  ref,
) {
  const Comp = asChild ? Slot : "button";
  return (
    <Comp
      ref={ref}
      className={cn(buttonVariants({ variant, size }), className)}
      disabled={asChild ? undefined : disabled || loading}
      {...props}
    >
      {asChild ? (
        children
      ) : (
        <>
          {loading ? <Loader2 aria-hidden="true" className="size-4 animate-spin" /> : null}
          {children}
        </>
      )}
    </Comp>
  );
});

// ---------------------------------------------------------------- Card

export function Card({ className, ...props }: ComponentProps<"section">) {
  return <section className={cn("rounded-xl border border-line bg-surface", className)} {...props} />;
}

export function CardHeader({
  title,
  description,
  actions,
  className,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-4", className)}>
      <div className="min-w-0">
        <h2 className="text-sm font-semibold tracking-wide text-fg">{title}</h2>
        {description ? <p className="mt-1 text-sm text-muted">{description}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}

export function CardBody({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("px-5 py-4", className)} {...props} />;
}

// ---------------------------------------------------------------- Badges

const SEV: Record<string, string> = {
  critical: "bg-sev-critical/15 text-sev-critical border-sev-critical/40",
  high: "bg-sev-high/15 text-sev-high border-sev-high/40",
  medium: "bg-sev-medium/15 text-sev-medium border-sev-medium/40",
  low: "bg-sev-low/15 text-sev-low border-sev-low/40",
  informational: "bg-sev-info/15 text-sev-info border-sev-info/40",
  unknown: "bg-sev-info/10 text-faint border-line",
};

export function Badge({ className, ...props }: ComponentProps<"span">) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border border-line px-1.5 py-0.5 text-xs font-medium leading-4 whitespace-nowrap",
        className,
      )}
      {...props}
    />
  );
}

export function SeverityBadge({ severity }: { severity: string }) {
  return <Badge className={cn("uppercase tracking-wide", SEV[severity] ?? SEV.unknown)}>{severity}</Badge>;
}

const STATUS_TONE: Record<string, string> = {
  passed: "text-ok border-ok/40 bg-ok/10",
  completed: "text-ok border-ok/40 bg-ok/10",
  succeeded: "text-ok border-ok/40 bg-ok/10",
  ready: "text-ok border-ok/40 bg-ok/10",
  observed: "text-sev-low border-sev-low/40 bg-sev-low/10",
  expected_revert: "text-sev-low border-sev-low/40 bg-sev-low/10",
  observed_revert: "text-warn border-warn/40 bg-warn/10",
  inferred: "text-sev-low border-sev-low/40 bg-sev-low/10",
  partial: "text-warn border-warn/40 bg-warn/10",
  inconclusive: "text-warn border-warn/40 bg-warn/10",
  rendering: "text-accent border-accent/40 bg-accent/10",
  running: "text-accent border-accent/40 bg-accent/10",
  queued: "text-muted border-line bg-surface-2",
  pending: "text-muted border-line bg-surface-2",
  skipped: "text-faint border-line bg-surface-2",
  unsupported: "text-faint border-line bg-surface-2",
  unavailable: "text-faint border-line bg-surface-2",
  cancelled: "text-faint border-line bg-surface-2",
  failed: "text-bad border-bad/40 bg-bad/10",
  unexpected_revert: "text-bad border-bad/40 bg-bad/10",
  infra_error: "text-bad border-bad/40 bg-bad/10",
  timed_out: "text-bad border-bad/40 bg-bad/10",
  rejected: "text-bad border-bad/40 bg-bad/10",
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const running = status === "running" || status === "rendering";
  return (
    <Badge className={cn(STATUS_TONE[status] ?? "text-muted", className)}>
      {running ? <Loader2 aria-hidden="true" className="size-3 animate-spin" /> : null}
      {status.replace(/_/g, " ")}
    </Badge>
  );
}

const TAG_TONE: Record<string, string> = {
  "on-chain": "text-accent border-accent/40",
  measured: "text-ok border-ok/40",
  hypothetical: "text-warn border-warn/40",
  unavailable: "text-faint border-line",
  "source-ast": "text-sev-low border-sev-low/40",
  bytecode: "text-sev-low border-sev-low/40",
  simulation: "text-ok border-ok/40",
  metadata: "text-muted border-line",
  "rpc-state": "text-accent border-accent/40",
};

/** Provenance / confidence-basis tag. */
export function TagBadge({ tag, title }: { tag: string; title?: string }) {
  return (
    <Badge className={cn("font-mono text-[11px]", TAG_TONE[tag] ?? "text-muted")} title={title}>
      {tag}
    </Badge>
  );
}

// ---------------------------------------------------------------- Copy / code

export function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="inline-flex size-7 shrink-0 items-center justify-center rounded text-faint hover:bg-surface-2 hover:text-fg"
      aria-label={done ? "Copied" : label}
      title={done ? "Copied" : label}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        } catch {
          /* clipboard unavailable (insecure context); nothing to do */
        }
      }}
    >
      {done ? <Check aria-hidden="true" className="size-3.5 text-ok" /> : <Copy aria-hidden="true" className="size-3.5" />}
    </button>
  );
}

export function Mono({ value, short = false, copy = true }: { value: string | null | undefined; short?: boolean; copy?: boolean }) {
  if (!value) return <span className="text-faint">—</span>;
  const shown = short && value.length > 14 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
  return (
    <span className="inline-flex min-w-0 max-w-full items-center gap-1 align-middle">
      <span className="truncate font-mono text-[13px]" title={value}>
        {shown}
      </span>
      {copy ? <CopyButton value={value} /> : null}
    </span>
  );
}

export function CodeBlock({ code, className, copy = true }: { code: string; className?: string; copy?: boolean }) {
  return (
    <div className={cn("relative rounded-lg border border-line bg-bg", className)}>
      {copy ? (
        <div className="absolute right-1.5 top-1.5">
          <CopyButton value={code} label="Copy code" />
        </div>
      ) : null}
      <pre className="overflow-x-auto p-3 pr-10 font-mono text-[12.5px] leading-relaxed text-fg/90">
        <code>{code}</code>
      </pre>
    </div>
  );
}

// ---------------------------------------------------------------- definition list

export function KV({ items, className }: { items: [ReactNode, ReactNode][]; className?: string }) {
  return (
    <dl className={cn("grid grid-cols-1 gap-x-6 gap-y-3 sm:grid-cols-[max-content_1fr]", className)}>
      {items.map(([k, v], i) => (
        <div key={i} className="contents">
          <dt className="text-xs uppercase tracking-wide text-faint sm:pt-0.5">{k}</dt>
          <dd className="min-w-0 text-sm text-fg">{v}</dd>
        </div>
      ))}
    </dl>
  );
}

// ---------------------------------------------------------------- states

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 py-8 text-sm text-muted">
      <Loader2 aria-hidden="true" className="size-4 animate-spin" />
      {label}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden="true" className={cn("animate-pulse rounded-md bg-surface-2", className)} />;
}

export function EmptyState({
  title,
  children,
  action,
  icon,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-12 text-center">
      <div className="text-faint">{icon ?? <Inbox aria-hidden="true" className="size-8" />}</div>
      <p className="text-sm font-medium text-fg">{title}</p>
      {children ? <div className="max-w-md text-sm text-muted">{children}</div> : null}
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry, title = "Could not load this data" }: { error: unknown; onRetry?: () => void; title?: string }) {
  const code = isApiError(error) ? error.code : null;
  const cid = isApiError(error) ? error.correlationId : null;
  return (
    <div role="alert" className="flex flex-col gap-3 rounded-lg border border-bad/40 bg-bad/5 p-4">
      <div className="flex items-start gap-2">
        <AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-bad" />
        <div className="min-w-0">
          <p className="text-sm font-medium text-fg">{title}</p>
          <p className="mt-1 break-words text-sm text-muted">{errorMessage(error)}</p>
          {code || cid ? (
            <p className="mt-1 font-mono text-xs text-faint">
              {code ? `code=${code}` : ""} {cid ? `correlation=${cid}` : ""}
            </p>
          ) : null}
        </div>
      </div>
      {onRetry ? (
        <div>
          <Button size="sm" onClick={onRetry}>
            <RefreshCw aria-hidden="true" className="size-3.5" /> Retry
          </Button>
        </div>
      ) : null}
    </div>
  );
}

export function Notice({ tone = "info", children, className }: { tone?: "info" | "warn" | "bad"; children: ReactNode; className?: string }) {
  const tones = {
    info: "border-line bg-surface-2 text-muted",
    warn: "border-warn/40 bg-warn/5 text-fg",
    bad: "border-bad/40 bg-bad/5 text-fg",
  };
  return <div className={cn("rounded-lg border px-4 py-3 text-sm", tones[tone], className)}>{children}</div>;
}

export function ProgressBar({ value, label }: { value: number; label: string }) {
  const v = Math.max(0, Math.min(1, value));
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(v * 100)}
      className="h-1.5 w-full overflow-hidden rounded-full bg-surface-2"
    >
      <div className="h-full rounded-full bg-accent transition-[width] duration-500" style={{ width: `${v * 100}%` }} />
    </div>
  );
}

export function PageHeader({ title, description, actions, eyebrow }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 pb-6">
      <div className="min-w-0">
        {eyebrow ? <div className="mb-1 text-xs font-medium uppercase tracking-wider text-accent">{eyebrow}</div> : null}
        <h1 className="text-2xl font-semibold tracking-tight text-fg">{title}</h1>
        {description ? <div className="mt-1.5 max-w-3xl text-sm text-muted">{description}</div> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}

// ---------------------------------------------------------------- form field

export function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div className="field flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-fg">
        {label}
      </label>
      {hint ? (
        <span id={`${id}-hint`} className="text-xs text-faint">
          {hint}
        </span>
      ) : null}
      {children}
      {error ? (
        <span id={`${id}-error`} role="alert" className="text-xs text-bad">
          {error}
        </span>
      ) : null}
    </div>
  );
}

export const inputClass =
  "field-input h-10 w-full rounded-md border border-line bg-bg px-3 text-sm text-fg placeholder:text-faint focus:border-accent focus:outline-none aria-[invalid=true]:border-bad";

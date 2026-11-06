/**
 * Scenario outcome classes for the Adversarial Lab, and the LP-facing explanation of each scenario.
 *
 * Statuses come from the backend (forge outcomes). This module only groups them for display; it
 * never upgrades a status: "unsupported" is never shown as passed, and "passed" only means the
 * scenario's assertions held at the forked block.
 */

export type OutcomeClass = "passed" | "failed" | "inconclusive" | "not_run" | "error" | "running";

const CLASS: Record<string, OutcomeClass> = {
  passed: "passed",
  expected_revert: "passed",
  failed: "failed",
  unexpected_revert: "failed",
  inconclusive: "inconclusive",
  partial: "inconclusive",
  unsupported: "not_run",
  skipped: "not_run",
  infra_error: "error",
  timed_out: "error",
  cancelled: "error",
  queued: "running",
  running: "running",
};

export function outcomeOf(status: string): OutcomeClass {
  return CLASS[status] ?? "inconclusive";
}

export const OUTCOMES: { id: OutcomeClass; label: string; tone: string; dot: string; meaning: string }[] = [
  {
    id: "failed",
    label: "Failed",
    tone: "text-bad border-bad/40 bg-bad/10",
    dot: "bg-bad",
    meaning: "An assertion failed or an operation reverted unexpectedly. Review the evidence: it is a lead, not a confirmed exploit.",
  },
  {
    id: "passed",
    label: "Passed",
    tone: "text-ok border-ok/40 bg-ok/10",
    dot: "bg-ok",
    meaning: "The scenario's assertions held at this fork block (including expected reverts). This is not proof that the hook is safe.",
  },
  {
    id: "inconclusive",
    label: "Inconclusive",
    tone: "text-warn border-warn/40 bg-warn/10",
    dot: "bg-warn",
    meaning: "The run finished but did not establish a result for every step.",
  },
  {
    id: "not_run",
    label: "Not run",
    tone: "text-muted border-line bg-surface-2",
    dot: "bg-line-strong",
    meaning: "Unsupported or skipped: the behaviour it needs was not detected, so no valid test was executed.",
  },
  {
    id: "error",
    label: "Error",
    tone: "text-warn border-warn/40 bg-warn/5",
    dot: "bg-warn",
    meaning: "Infrastructure outcome (RPC, timeout, cancellation). Nothing can be concluded about the hook.",
  },
  {
    id: "running",
    label: "Running",
    tone: "text-accent border-accent/40 bg-accent/10",
    dot: "bg-accent",
    meaning: "Queued or executing on the fork.",
  },
];

export const OUTCOME = Object.fromEntries(OUTCOMES.map((o) => [o.id, o])) as Record<OutcomeClass, (typeof OUTCOMES)[number]>;

/** Explanatory copy only (what the scenario means for an LP); results always come from the API. */
export const SCENARIO_LP: Record<string, { short: string; why: string }> = {
  withdrawal_failure: {
    short: "Withdrawal",
    why: "If removing liquidity reverts, your position cannot be withdrawn while that condition holds.",
  },
  oracle_failure: {
    short: "Oracle",
    why: "A hook that reads a price feed inside callbacks can block swaps or withdrawals when the feed is stale, zero or reverts.",
  },
  fee_escalation: {
    short: "Fees",
    why: "A dynamic fee changes what traders pay, and so your fee income and volume. The test shows who can change it and within which bounds.",
  },
  admin_upgrade: {
    short: "Admin",
    why: "Privileged calls can change how the hook behaves after you deposit. The test shows which calls are accepted, and from whom.",
  },
  accounting_invariants: {
    short: "Accounting",
    why: "Return deltas let a hook change settled amounts. The test checks that balance changes match the pool's accounting.",
  },
  transaction_ordering: {
    short: "Ordering",
    why: "Outcomes can depend on the order of operations. The test reports the measured differences between orderings, nothing more.",
  },
};

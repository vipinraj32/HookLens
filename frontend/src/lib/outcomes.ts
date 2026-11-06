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
    meaning: "An assertion failed or a step reverted unexpectedly. A lead to review, not a confirmed exploit.",
  },
  {
    id: "passed",
    label: "Passed",
    tone: "text-ok border-ok/40 bg-ok/10",
    dot: "bg-ok",
    meaning: "Assertions held at this fork block. Not proof the hook is safe.",
  },
  {
    id: "inconclusive",
    label: "Inconclusive",
    tone: "text-warn border-warn/40 bg-warn/10",
    dot: "bg-warn",
    meaning: "Finished without a result for every step.",
  },
  {
    id: "not_run",
    label: "Not run",
    tone: "text-muted border-line bg-surface-2",
    dot: "bg-line-strong",
    meaning: "Required behaviour not detected, so no valid test ran.",
  },
  {
    id: "error",
    label: "Error",
    tone: "text-warn border-warn/40 bg-warn/5",
    dot: "bg-warn",
    meaning: "RPC, timeout or cancellation. Says nothing about the hook.",
  },
  {
    id: "running",
    label: "Running",
    tone: "text-accent border-accent/40 bg-accent/10",
    dot: "bg-accent",
    meaning: "Queued or executing.",
  },
];

export const OUTCOME = Object.fromEntries(OUTCOMES.map((o) => [o.id, o])) as Record<OutcomeClass, (typeof OUTCOMES)[number]>;

/** The LP question each scenario answers (explanatory copy; results always come from the API). */
export const SCENARIO_LP: Record<string, { short: string; why: string }> = {
  withdrawal_failure: {
    short: "Withdrawal",
    why: "Can you always withdraw?",
  },
  oracle_failure: {
    short: "Oracle",
    why: "Does a bad price feed block swaps or exits?",
  },
  fee_escalation: {
    short: "Fees",
    why: "Who can change the fee, and how far?",
  },
  admin_upgrade: {
    short: "Admin",
    why: "What can the owner change after you deposit?",
  },
  accounting_invariants: {
    short: "Accounting",
    why: "Do balances match the pool's accounting?",
  },
  transaction_ordering: {
    short: "Ordering",
    why: "Does operation order change the outcome?",
  },
};

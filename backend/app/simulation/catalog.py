"""Scenario catalogue: the Foundry entry points the backend can execute.

Each scenario maps to an env-driven contract in contracts/test/scenarios/HookLensScenarios.t.sol.
Descriptions state exactly what is executed; none of them claims to prove a hook safe.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScenarioDef:
    scenario_id: str
    title: str
    contract: str
    test: str
    description: str
    executes: tuple[str, ...]
    result_file: str


SCENARIOS: dict[str, ScenarioDef] = {
    s.scenario_id: s
    for s in (
        ScenarioDef(
            "fee_escalation",
            "Fee escalation",
            "FeeEscalationScenario",
            "test_feeEscalation",
            "Measures the LP fee charged on real swaps, then calls the detected fee setters from an unprivileged "
            "account and from the detected owner (impersonated in the fork only) and re-measures.",
            (
                "baseline swaps with fee read from the PoolManager Swap event",
                "unauthorized fee-setter calls",
                "authorized fee-setter calls at the detected bounds",
                "swaps after each successful change",
            ),
            "fee_escalation.json",
        ),
        ScenarioDef(
            "withdrawal_failure",
            "Withdrawal failure",
            "WithdrawalFailureScenario",
            "test_withdrawalFailure",
            "Adds liquidity, swaps, removes partially and fully, repeats; then re-tests removal under each "
            "dependency condition detected by static analysis (oracle failure, pause, external call failure) "
            "and checks recovery.",
            (
                "add / partial remove / full remove / repeat",
                "removal under each detected condition",
                "recovery after the condition clears",
            ),
            "withdrawal_failure.json",
        ),
        ScenarioDef(
            "oracle_failure",
            "Oracle failure",
            "OracleFailureScenario",
            "test_oracleFailure",
            "Mocks the detected oracle to revert, return zero, return a negative answer, go stale and jump 10x, "
            "and records swap, add and remove behaviour under each; also tests removal before and after an "
            "oracle refresh.",
            (
                "oracle revert / zero / negative / stale / 10x jump",
                "swap, add and remove under each condition",
                "update ordering",
            ),
            "oracle_failure.json",
        ),
        ScenarioDef(
            "accounting_invariants",
            "Accounting invariants",
            "AccountingInvariantScenario",
            "test_accounting",
            "Executes adds, removes, exact-input and exact-output swaps with several actors and checks that each "
            "actor's balance change equals the BalanceDelta, and that tokens are conserved across actors, the "
            "PoolManager and the hook (including ERC-6909 claims).",
            ("multi-actor add/remove", "exact-in and exact-out swaps both directions", "conservation checks"),
            "accounting_invariants.json",
        ),
        ScenarioDef(
            "admin_upgrade",
            "Admin & upgrade",
            "AdminUpgradeScenario",
            "test_adminUpgrade",
            "Calls detected privileged functions from an unprivileged account and from the detected owner; for "
            "upgradeable hooks, upgrades to a deliberately reverting implementation and tests liquidity removal.",
            (
                "unauthorized privileged calls",
                "authorized privileged calls (fork-only impersonation)",
                "upgrade to a reverting implementation, then removal",
            ),
            "admin_upgrade.json",
        ),
        ScenarioDef(
            "transaction_ordering",
            "Transaction ordering",
            "TransactionOrderingScenario",
            "test_ordering",
            "Compares a single swap with the same amount split in two, liquidity added before versus after swaps, "
            "and round-trip swaps. Reports measured differences only.",
            ("single vs split swap", "LP before vs after swaps", "round trips"),
            "transaction_ordering.json",
        ),
    )
}

DEFAULT_ORDER = (
    "withdrawal_failure",
    "oracle_failure",
    "fee_escalation",
    "admin_upgrade",
    "accounting_invariants",
    "transaction_ordering",
)

# Final statuses for a scenario run.
STATUSES = (
    "passed",
    "failed",
    "expected_revert",
    "unexpected_revert",
    "inconclusive",
    "unsupported",
    "skipped",
    "timed_out",
    "cancelled",
    "partial",
    "infra_error",
)

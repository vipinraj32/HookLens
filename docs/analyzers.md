# Analyzers

The analyzers are deterministic. The same contract version and inputs always produce the same
finding IDs, severities and evidence IDs. There are no scores and no confidence percentages.

## Finding model

| Field | Meaning |
|---|---|
| `finding_id` | `HL-<CODE>-<sha1(scope, rule, location)[:8]>`. Stable across re-scans of the same code |
| `severity` | `critical`, `high`, `medium`, `low`, `informational` or `unknown`. Assigned by fixed rules, each with a written `severity_rationale` |
| `confidence_basis` | What the claim rests on: `source-ast`, `bytecode`, `rpc-state`, `simulation` or `metadata` |
| `status` | `inferred` (static), `observed` (executed in a simulation) or `needs-review` |
| `evidence_ids` | `EV-…` records with source lines, bytecode facts, permission bits, RPC state or simulation steps |
| `related_scenarios` | Lab scenarios that exercise the finding |
| `lp_implications`, `remediation`, `limitations` | Plain-language context, always stated next to the claim |

`unknown` is used when the code that would decide the question cannot be analysed. A typical case
is a dynamic-fee or withdrawal callback on an unverified contract. HookLens does not guess.

An analyzer that raises is recorded as an `analyzer_error` run, and the scan ends as `partial`. The
other analyzers still run.

## Inputs

- **Permission bits.** Decoded from the low 14 bits of the hook address. The constants in
  `packages/hooklens/src/hooklens/analyzers/permissions_generated.py` are generated from the
  vendored `lib/v4-core/src/libraries/Hooks.sol` by `backend/scripts/gen_permissions.py`, and
  `backend/tests/test_permissions_bytecode.py` fails if they drift.
- **Bytecode** (`bytecode.py`). A disassembler extracts:
  - dispatcher selectors
  - CALL, DELEGATECALL, STATICCALL, CREATE, CREATE2 and SELFDESTRUCT presence
  - PUSH20 constants
  - the CBOR metadata hash
- **Source AST** (`source/ast_index.py`). This applies to verified or locally matched source only.
  It provides:
  - functions and modifiers
  - the internal call graph
  - state reads and writes
  - external calls, with their target state variable and whether they sit in a try/catch
  - revert sites
  - access guards (`msg.sender` checks and `onlyOwner`-style modifiers)
- **RPC state.** Storage values such as the owner and the oracle address, read at the pinned block.

## Rules

| Code | Family | Rules |
|---|---|---|
| PRM | Permissions | `enabled_callbacks` (info). `invalid_hook_address` (info). `enabled_callback_missing_selector` (medium). `declared_permissions_mismatch` (medium). `return_delta_*` (one per enabled return-delta flag) |
| ACC | Access control | `privileged_functions` (info). `privileged_state_in_callback` (medium if it affects removal, otherwise low). `pause_mechanism` (medium if it gates removal, otherwise low). `tx_origin_auth` (low) |
| FEE | Dynamic fee | `dynamic_fee_control` (the mechanism, fee state variables, setters and their bound checks). `dynamic_fee_unverified` (unknown) |
| ORC | Oracle | `oracle_dependency` (which callbacks read an oracle and what freshness or zero checks exist). `oracle_replaceable` (high if the setter is unguarded, otherwise low) |
| EXT | External calls | `callback_external_calls`: calls and delegatecalls reachable from callbacks, and whether they are in try/catch |
| WDR | Withdrawal | `withdrawal_revert_conditions`: every condition found that can revert `before`/`afterRemoveLiquidity`. `withdrawal_callback_unverified` (unknown) |
| ACT | Accounting | `custom_accounting`: `take`, `settle`, `mint` and `burn` on the PoolManager, and return deltas |
| UPG | Upgradeability | `upgradeable_proxy`. `uups_upgrade_function` (low). `selfdestruct_present` (low) |
| SRC | Source integrity | `source_unavailable` (info). `bytecode_match_*`: whether the verified or local source matches the runtime code |
| BYT | Bytecode-only | `admin_selectors` (unknown). `delegatecall_present` (unknown). These run when no source is available |

Severities that depend on context are computed by the rule (for example, whether a removal path is
affected), and the rationale string explains which case applied.

## What the analyzers do not do

- Prove the absence of vulnerabilities. A clean scan means none of these rules matched.
- Analyse contracts the hook calls, beyond recording the calls.
- Run symbolic execution. Slither is not integrated.
- Analyse bytecode-only hooks in depth. They get permission checks, selector checks and opcode
  presence checks, and anything else is reported as `unknown`.

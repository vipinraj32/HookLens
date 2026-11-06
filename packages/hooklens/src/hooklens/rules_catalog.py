"""Static descriptions of HookLens rules, used for SARIF rule metadata and report legends.

Rule identifiers are ``HL.<ANALYZER CODE>.<rule_id>`` and never change meaning between versions;
new behaviour gets a new rule id. Descriptions describe the *pattern*, never a confirmed exploit.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuleInfo:
    name: str
    short: str
    help: str


ANALYZER_CODES = {
    "SRC": "source_integrity",
    "PRM": "permissions",
    "BYT": "bytecode_heuristics",
    "ACC": "access_control",
    "UPG": "upgradeability",
    "EXT": "external_calls",
    "ORC": "oracle",
    "FEE": "dynamic_fee",
    "WDR": "withdrawal",
    "ACT": "accounting",
}

_RULES: dict[str, RuleInfo] = {
    "PRM.enabled_callbacks": RuleInfo(
        "EnabledCallbacks",
        "Pool operations during which hook code executes",
        "Lists the callbacks enabled by the hook's permissions. Informational: it defines where hook code runs, "
        "not whether that code is harmful.",
    ),
    "PRM.permissions_undetermined": RuleInfo(
        "PermissionsUndetermined",
        "Hook permissions cannot be determined from source",
        "Neither literal declared permissions nor implemented callbacks were found (e.g. a proxy); the deployed "
        "address bits decide which callbacks run.",
    ),
    "PRM.invalid_hook_address": RuleInfo(
        "InvalidHookAddress",
        "Address bits are not a valid v4 hook configuration",
        "Hooks.isValidHookAddress would reject the address, so pools cannot be initialised with it.",
    ),
    "PRM.invalid_permission_set": RuleInfo(
        "InvalidPermissionSet",
        "Declared permissions are not a valid v4 hook configuration",
        "A return-delta flag is declared without its base callback flag; Hooks.isValidHookAddress rejects this.",
    ),
    "PRM.enabled_callback_missing_selector": RuleInfo(
        "EnabledCallbackMissing",
        "An enabled callback is not implemented",
        "The PoolManager would call a callback whose selector is absent from the contract dispatcher, so the "
        "operation would revert or reach the fallback.",
    ),
    "PRM.declared_permissions_mismatch": RuleInfo(
        "DeclaredPermissionsMismatch",
        "Declared permissions differ from the address bits",
        "The PoolManager follows address bits, not getHookPermissions(); behaviour differs from the declaration.",
    ),
    "PRM.return_delta": RuleInfo(
        "ReturnDeltaPermission",
        "Return-delta permission enabled",
        "The hook may return deltas that change what swappers or LPs pay or receive. Legitimate v4 feature; "
        "review the delta computation.",
    ),
    "SRC.source_unavailable": RuleInfo(
        "SourceUnavailable", "Verified source unavailable", "Analysis was limited to bytecode."
    ),
    "SRC.bytecode_match": RuleInfo(
        "SourceBytecodeCorrespondence",
        "Correspondence between verified source and deployed bytecode",
        "Whether recompiled verified source reproduces the deployed runtime bytecode.",
    ),
    "BYT.admin_selectors": RuleInfo(
        "AdminSelectors", "Administrative selectors in bytecode", "Recognised admin functions without source."
    ),
    "BYT.delegatecall_present": RuleInfo(
        "DelegatecallPresent", "DELEGATECALL in non-proxy hook code", "Delegatecall can execute foreign code."
    ),
    "ACC.privileged_functions": RuleInfo(
        "PrivilegedFunctions",
        "Caller-restricted state-changing functions",
        "Functions restricted to specific callers (owner, roles). Informational inventory of admin powers.",
    ),
    "ACC.privileged_state_in_callback": RuleInfo(
        "PrivilegedStateInCallback",
        "Privileged configuration influences a callback",
        "A state variable written by a caller-restricted function is read by a hook callback, so an admin can "
        "change how swaps or liquidity operations behave.",
    ),
    "ACC.pause_mechanism": RuleInfo(
        "PauseMechanism",
        "Pause mechanism present",
        "A privileged account can pause hook behaviour; when the pause gates liquidity removal it can block LP "
        "withdrawals.",
    ),
    "ACC.tx_origin_auth": RuleInfo(
        "TxOriginAuth", "tx.origin used for authorization", "tx.origin checks can be satisfied via phishing."
    ),
    "UPG.upgradeable_proxy": RuleInfo(
        "UpgradeableProxy", "Hook logic is upgradeable", "The deployed hook is a proxy whose logic can change."
    ),
    "UPG.uups_upgrade_function": RuleInfo(
        "UpgradeFunction", "Contract exposes an upgrade function", "Upgrade functions can change behaviour."
    ),
    "UPG.delegating_proxy_source": RuleInfo(
        "DelegatingProxy",
        "Contract is a delegating proxy",
        "The fallback forwards calls with DELEGATECALL, so hook behaviour is defined by a replaceable implementation.",
    ),
    "UPG.unguarded_initializer": RuleInfo(
        "UnguardedInitializer",
        "Initializer sets a privileged role without a caller check",
        "The first caller of initialize() becomes the privileged role unless initialisation is atomic with deployment.",
    ),
    "UPG.selfdestruct_present": RuleInfo(
        "SelfdestructPresent", "SELFDESTRUCT opcode present", "SELFDESTRUCT can move the contract's ETH balance."
    ),
    "EXT.callback_external_calls": RuleInfo(
        "CallbackExternalCalls",
        "Hook callback makes external calls",
        "External calls inside callbacks add dependencies: a reverting or reentrant callee can block or alter "
        "the pool operation.",
    ),
    "ORC.oracle_dependency": RuleInfo(
        "OracleDependency",
        "Callback depends on an external oracle",
        "A callback reads an external price feed; stale, zero or reverting answers can block or misprice the "
        "operation.",
    ),
    "ORC.oracle_replaceable": RuleInfo(
        "OracleReplaceable",
        "Oracle address can be replaced",
        "The oracle used by callbacks can be changed; whoever controls the setter controls the price input.",
    ),
    "FEE.dynamic_fee_control": RuleInfo(
        "DynamicFeeControl",
        "Hook controls the LP fee applied to swaps",
        "The hook sets or overrides the LP fee; review who can change it and the bounds that apply.",
    ),
    "FEE.dynamic_fee_unverified": RuleInfo(
        "DynamicFeeUnverified", "Dynamic fee controlled by unverified code", "Fee logic could not be inspected."
    ),
    "WDR.withdrawal_revert_conditions": RuleInfo(
        "WithdrawalRevertConditions",
        "Callback can revert liquidity removal",
        "Revert conditions inside remove-liquidity callbacks can block LP withdrawals when they hold.",
    ),
    "WDR.withdrawal_callback_unverified": RuleInfo(
        "WithdrawalCallbackUnverified", "Liquidity removal runs unverified code", "Withdrawal logic not inspected."
    ),
    "ACT.custom_accounting": RuleInfo(
        "CustomAccounting",
        "Callback moves currency through the PoolManager",
        "The hook settles, takes or mints currency during a callback; custom accounting must keep balances "
        "consistent with the deltas it returns.",
    ),
}


def rule_key(code: str, rule_id: str) -> str:
    return f"HL.{code}.{rule_id}"


def rule_info(code: str, rule_id: str) -> RuleInfo:
    key = f"{code}.{rule_id}"
    if key in _RULES:
        return _RULES[key]
    for prefix in ("return_delta", "bytecode_match"):
        if rule_id.startswith(prefix) and f"{code}.{prefix}" in _RULES:
            return _RULES[f"{code}.{prefix}"]
    words = rule_id.replace("_", " ")
    return RuleInfo("".join(w.capitalize() for w in rule_id.split("_")), words.capitalize(), words.capitalize())

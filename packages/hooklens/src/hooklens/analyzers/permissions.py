"""Uniswap v4 hook permission decoding.

The PoolManager decides which callbacks to invoke from the low 14 bits of the hook address.
Constants come from `permissions_generated.py`, generated from the pinned v4-core sources.

Permissions only determine *which callbacks can execute*. They do not establish whether a
hook is dangerous; every explanation produced here says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from hooklens.analyzers import permissions_generated as gen


@dataclass(frozen=True)
class Permission:
    flag: str
    bit: int
    field: str
    callback: str
    signature: str
    selector: str
    enabled: bool

    @property
    def is_return_delta(self) -> bool:
        return self.flag.endswith("RETURNS_DELTA")

    def to_dict(self) -> dict[str, Any]:
        return {
            "flag": self.flag,
            "bit": self.bit,
            "field": self.field,
            "callback": self.callback,
            "signature": self.signature,
            "selector": self.selector,
            "enabled": self.enabled,
            "is_return_delta": self.is_return_delta,
        }


OPERATION_FOR_CALLBACK = {
    "beforeInitialize": "initialize",
    "afterInitialize": "initialize",
    "beforeAddLiquidity": "add_liquidity",
    "afterAddLiquidity": "add_liquidity",
    "beforeRemoveLiquidity": "remove_liquidity",
    "afterRemoveLiquidity": "remove_liquidity",
    "beforeSwap": "swap",
    "afterSwap": "swap",
    "beforeDonate": "donate",
    "afterDonate": "donate",
}

FLAG_EXPLANATIONS = {
    "BEFORE_INITIALIZE": "Runs before a pool using this hook is initialised; it can reject initialisation.",
    "AFTER_INITIALIZE": "Runs after initialisation; it can revert, blocking pool creation.",
    "BEFORE_ADD_LIQUIDITY": "Runs before every liquidity addition; it can revert to block deposits.",
    "AFTER_ADD_LIQUIDITY": "Runs after every liquidity addition; it can revert the deposit.",
    "BEFORE_REMOVE_LIQUIDITY": "Runs before every liquidity removal; a revert here blocks LP withdrawals.",
    "AFTER_REMOVE_LIQUIDITY": "Runs after every liquidity removal; a revert here also blocks withdrawals.",
    "BEFORE_SWAP": "Runs before every swap; it can override the LP fee on dynamic-fee pools or revert swaps.",
    "AFTER_SWAP": "Runs after every swap; it can revert the swap.",
    "BEFORE_DONATE": "Runs before donations.",
    "AFTER_DONATE": "Runs after donations.",
    "BEFORE_SWAP_RETURNS_DELTA": "beforeSwap may return a delta that changes swap amounts (custom curves, NoOp swaps).",
    "AFTER_SWAP_RETURNS_DELTA": "afterSwap may return a delta that charges or credits the swapper in the unspecified token.",
    "AFTER_ADD_LIQUIDITY_RETURNS_DELTA": "afterAddLiquidity may return a delta that changes what the LP pays on deposit.",
    "AFTER_REMOVE_LIQUIDITY_RETURNS_DELTA": "afterRemoveLiquidity may return a delta that changes what the LP receives on withdrawal.",
}


def decode(address: str) -> list[Permission]:
    value = int(address, 16)
    return [
        Permission(
            flag=flag,
            bit=bit,
            field=field,
            callback=cb,
            signature=sig,
            selector=sel,
            enabled=bool(value & (1 << bit)),
        )
        for flag, bit, field, cb, sig, sel in gen.FLAGS
    ]


def summarize(perms: list[Permission]) -> dict[str, Any]:
    enabled = [p for p in perms if p.enabled]
    callbacks = sorted({p.callback for p in enabled})
    operations = sorted({OPERATION_FOR_CALLBACK[c] for c in callbacks})
    return {
        "v4_core_commit": gen.V4_CORE_COMMIT,
        "hooks_sol_sha256": gen.HOOKS_SOL_SHA256,
        "bits": hex(sum(1 << p.bit for p in enabled)),
        "flags": [p.to_dict() | {"explanation": FLAG_EXPLANATIONS[p.flag]} for p in perms],
        "enabled_flags": [p.flag for p in enabled],
        "callbacks": callbacks,
        "affected_operations": operations,
        "return_delta_flags": [p.flag for p in enabled if p.is_return_delta],
        "can_affect_withdrawals": any(p.callback in ("beforeRemoveLiquidity", "afterRemoveLiquidity") for p in enabled),
        "note": (
            "Permission bits determine which callbacks the PoolManager will invoke. They do not by "
            "themselves establish that a hook is harmful."
        ),
    }


def from_flags(enabled: dict[str, bool]) -> list[Permission]:
    """Permission list from Hooks.Permissions field values (e.g. a declared getHookPermissions())."""
    return [
        Permission(
            flag=flag,
            bit=bit,
            field=field,
            callback=cb,
            signature=sig,
            selector=sel,
            enabled=bool(enabled.get(field, False)),
        )
        for flag, bit, field, cb, sig, sel in gen.FLAGS
    ]


def is_valid_hook_address(address: str, fee: int | None = None) -> tuple[bool, str]:
    """Mirror of Hooks.isValidHookAddress: return-delta flags require their base flag."""
    return is_valid_permission_set(decode(address), fee)


def is_valid_permission_set(
    permissions: list[Permission], fee: int | None = None, *, require_any: bool = True
) -> tuple[bool, str]:
    perms = {p.flag: p.enabled for p in permissions}
    pairs = [
        ("BEFORE_SWAP_RETURNS_DELTA", "BEFORE_SWAP"),
        ("AFTER_SWAP_RETURNS_DELTA", "AFTER_SWAP"),
        ("AFTER_ADD_LIQUIDITY_RETURNS_DELTA", "AFTER_ADD_LIQUIDITY"),
        ("AFTER_REMOVE_LIQUIDITY_RETURNS_DELTA", "AFTER_REMOVE_LIQUIDITY"),
    ]
    for delta, base in pairs:
        if perms[delta] and not perms[base]:
            return False, f"{delta} is set without {base}"
    # A non-zero hook address must set at least one flag, unless the pool uses a dynamic fee.
    if require_any and not any(perms.values()) and fee != 0x800000:
        return False, "a hook address must set at least one permission flag (or use a dynamic fee)"
    return True, "valid"

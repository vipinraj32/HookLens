"""Shared helpers for source-based analyzers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.analyzers.context import AnalysisContext
from app.analyzers.source.ast_index import ExternalCall, FunctionInfo, RevertSite

PRIV_MODIFIER_RE = re.compile(r"^(only|auth|requires?Auth|requiresRole|restricted|isAuthorized|onlyRole)", re.I)
ROLE_NAMES = ("owner", "admin", "governance", "governor", "guardian", "operator", "manager", "controller", "keeper")
WITHDRAWAL_CALLBACKS = ("beforeRemoveLiquidity", "afterRemoveLiquidity")
SWAP_CALLBACKS = ("beforeSwap", "afterSwap")
ADD_CALLBACKS = ("beforeAddLiquidity", "afterAddLiquidity")


@dataclass
class Guard:
    function: FunctionInfo
    kind: str  # sender-check | modifier | role | pool-manager-only
    variables: list[str] = field(default_factory=list)
    modifiers: list[str] = field(default_factory=list)
    expressions: list[str] = field(default_factory=list)

    @property
    def privileged(self) -> bool:
        return self.kind != "pool-manager-only"

    def to_dict(self) -> dict[str, Any]:
        return {
            "function": self.function.signature,
            "kind": self.kind,
            "variables": self.variables,
            "modifiers": self.modifiers,
            "expressions": self.expressions[:4],
        }


def guard_of(ctx: AnalysisContext, fi: FunctionInfo) -> Guard | None:
    """Caller restriction of a function, derived from msg.sender checks in its closure."""
    assert ctx.index is not None
    closure = ctx.index.closure(fi)
    var_names: list[str] = []
    exprs: list[str] = []
    pm_only = True
    any_check = False
    for f in closure:
        for text, _loc, refs in f.sender_checks:
            any_check = True
            exprs.append(text)
            names = []
            for r in refs:
                node = ctx.index.nodes.get(r) or {}
                if node.get("nodeType") == "VariableDeclaration":
                    names.append(str(node.get("name")))
            if not any(ctx.is_pool_manager_var(r) for r in refs) and "poolmanager" not in text.lower():
                pm_only = False
            var_names.extend(names)
        if any(m in ("hasRole", "_checkRole", "onlyRole") for m in f.identifiers | f.member_names):
            any_check, pm_only = True, False
            exprs.append("role check (hasRole/_checkRole)")
    mods = [m for m in fi.modifiers if PRIV_MODIFIER_RE.match(m)]
    if not any_check and not mods:
        return None
    if any_check and pm_only and all("poolmanager" in m.lower() for m in mods):
        return Guard(fi, "pool-manager-only", sorted(set(var_names)), fi.modifiers, exprs)
    kind = "role" if any("role" in e.lower() for e in exprs) else ("sender-check" if any_check else "modifier")
    return Guard(fi, kind, sorted(set(v for v in var_names if v)), mods or fi.modifiers, exprs)


def callback_closure(ctx: AnalysisContext, callback: str) -> list[FunctionInfo]:
    assert ctx.index is not None
    fi = ctx.index.resolve(callback)
    return ctx.index.closure(fi) if fi else []


def external_calls_in(closure: list[FunctionInfo]) -> list[tuple[FunctionInfo, ExternalCall]]:
    return [(f, c) for f in closure for c in f.external_calls]


def reverts_in(closure: list[FunctionInfo]) -> list[tuple[FunctionInfo, RevertSite]]:
    return [(f, r) for f in closure for r in f.reverts]


def state_reads(closure: list[FunctionInfo]) -> set[int]:
    out: set[int] = set()
    for f in closure:
        out |= f.state_reads
    return out


def state_writers(ctx: AnalysisContext) -> dict[int, list[FunctionInfo]]:
    """state var id -> externally callable functions whose closure writes it."""
    assert ctx.index is not None
    out: dict[int, list[FunctionInfo]] = {}
    for fi in ctx.index.public_functions():
        if fi.mutability in ("view", "pure"):
            continue
        for f in ctx.index.closure(fi):
            for sv in f.state_writes:
                out.setdefault(sv, [])
                if fi not in out[sv]:
                    out[sv].append(fi)
    return out


def var_name(ctx: AnalysisContext, sv_id: int) -> str:
    assert ctx.index is not None
    sv = ctx.index.state_var(sv_id)
    if sv:
        return sv.name
    return str((ctx.index.nodes.get(sv_id) or {}).get("name", f"var#{sv_id}"))


def is_callback(name: str) -> bool:
    return name in (
        "beforeInitialize",
        "afterInitialize",
        "beforeAddLiquidity",
        "afterAddLiquidity",
        "beforeRemoveLiquidity",
        "afterRemoveLiquidity",
        "beforeSwap",
        "afterSwap",
        "beforeDonate",
        "afterDonate",
    )


def encode_probe_args(params: list[tuple[str, str]]) -> tuple[list[str], list[Any]] | None:
    """Benign ABI arguments for calling a privileged function in a fork, or None if unsupported."""
    types: list[str] = []
    values: list[Any] = []
    for _name, t in params:
        t = t.replace("contract ", "").strip()
        base = t.split(" ")[0]
        if base.startswith("uint") or base.startswith("int"):
            types.append(base)
            values.append(1)
        elif base == "bool":
            types.append("bool")
            values.append(True)
        elif base == "address" or (t and t[0].isupper() and " " not in t):  # interface/contract types
            types.append("address")
            values.append("0x000000000000000000000000000000000000bEEF")
        elif base == "bytes32":
            types.append("bytes32")
            values.append(b"\x00" * 32)
        else:
            return None
    return types, values

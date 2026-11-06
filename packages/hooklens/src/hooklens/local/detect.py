"""Identify Uniswap v4 hook contracts in compiled ASTs.

Classification (with the evidence behind it, never a bare label):

* ``hook``       concrete contract in the IHooks hierarchy (directly or via a BaseHook) that
                 declares permissions and/or implements callbacks. Confidence ``high``.
* ``candidate``  concrete contract that looks like a hook without the IHooks hierarchy: callback
                 functions taking a PoolKey, or a getHookPermissions() returning Hooks.Permissions,
                 or a delegating proxy that could be the address registered with the PoolManager.
                 Confidence ``medium`` or ``low``; the reasons say why.
* ``abstract-hook`` abstract hook base (analysed through the concrete hooks that inherit it).
* ``mock``       hook-like contract whose name or path marks it as a mock / test double.
* ``interface`` / ``library`` / ``not-a-hook``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

CALLBACKS = (
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
_MOCK_NAME = re.compile(r"(^Mock|Mock$|^Fake|^Stub|^Test[A-Z]|Harness$)")
_MOCK_PATH = re.compile(r"(^|/)(mocks?|test|tests|testing)/", re.I)


@dataclass
class ContractInfo:
    name: str
    file: str
    line: int
    kind: str
    confidence: str | None
    reasons: list[str] = field(default_factory=list)
    bases: list[str] = field(default_factory=list)
    callbacks: list[str] = field(default_factory=list)
    node_id: int = 0
    group: str = ""  # solc version of the compile group

    @property
    def analysable(self) -> bool:
        return self.kind in ("hook", "candidate")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "file": self.file,
            "line": self.line,
            "kind": self.kind,
            "confidence": self.confidence,
            "reasons": self.reasons,
            "bases": self.bases,
            "callbacks_implemented": self.callbacks,
        }


def _iter(node: Any) -> Any:
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, dict):
            yield n
            stack.extend(v for v in n.values() if isinstance(v, (dict, list)))
        elif isinstance(n, list):
            stack.extend(n)


def _line(sources: dict[str, str], file: str, src: str) -> int:
    try:
        start = int(src.split(":")[0])
    except (ValueError, IndexError):
        return 0
    return sources.get(file, "").encode("utf-8")[:start].count(b"\n") + 1


def detect(output: dict[str, Any], sources: dict[str, str], targets: list[str]) -> list[ContractInfo]:
    contracts: dict[int, dict[str, Any]] = {}
    file_of: dict[int, str] = {}
    for path, out in (output.get("sources") or {}).items():
        for n in _iter(out.get("ast") or {}):
            if n.get("nodeType") == "ContractDefinition" and isinstance(n.get("id"), int):
                contracts[n["id"]] = n
                file_of[n["id"]] = path
    results: list[ContractInfo] = []
    for cid, c in contracts.items():
        path = file_of[cid]
        if path not in targets:
            continue
        results.append(_classify(c, contracts, path, sources))
    results.sort(key=lambda r: (r.file, r.line))
    return results


def _classify(
    c: dict[str, Any], contracts: dict[int, dict[str, Any]], path: str, sources: dict[str, str]
) -> ContractInfo:
    name = str(c.get("name"))
    kind_raw = c.get("contractKind")
    info = ContractInfo(
        name, path, _line(sources, path, str(c.get("src", "0:0:0"))), "not-a-hook", None, node_id=c["id"]
    )
    lin = [contracts[i] for i in c.get("linearizedBaseContracts") or [] if i in contracts]
    info.bases = [str(b.get("name")) for b in lin[1:]]
    if kind_raw == "interface":
        info.kind = "interface"
        return info
    if kind_raw == "library":
        info.kind = "library"
        return info

    in_ihooks = any(b.get("name") == "IHooks" for b in lin[1:])
    base_hook = next((b.get("name") for b in lin[1:] if re.search(r"BaseHook", str(b.get("name")))), None)
    fns = [n for b in lin for n in b.get("nodes", []) if n.get("nodeType") == "FunctionDefinition"]
    own_fns = [n for n in c.get("nodes", []) if n.get("nodeType") == "FunctionDefinition"]
    declares_perms = any(
        n.get("name") == "getHookPermissions"
        and "Hooks.Permissions" in str(n.get("returnParameters"))
        and (n.get("implemented") or n.get("body"))
        for n in fns
    )
    poolkey_cbs = sorted(
        {
            str(n.get("name")).lstrip("_")
            for n in fns
            if str(n.get("name")).lstrip("_") in CALLBACKS
            and (n.get("body") is not None)
            and "struct PoolKey" in str(n.get("parameters"))
        }
    )
    # Callbacks the contract (or a project-local base) actually overrides, not the BaseHook defaults.
    overridden = sorted(
        {
            str(n.get("name")).lstrip("_")
            for b in lin
            if not _is_dependency_base(b)
            for n in b.get("nodes", [])
            if n.get("nodeType") == "FunctionDefinition"
            and str(n.get("name")).lstrip("_") in CALLBACKS
            and n.get("body") is not None
            and not _only_reverts(n)
        }
    )
    info.callbacks = overridden or poolkey_cbs
    delegating = _delegating_fallback(own_fns)
    abstract = bool(c.get("abstract"))

    reasons: list[str] = []
    if in_ihooks:
        reasons.append("inherits IHooks" + (f" via {base_hook}" if base_hook else ""))
    elif base_hook:
        reasons.append(f"inherits {base_hook}")
    if declares_perms:
        reasons.append("implements getHookPermissions() returning Hooks.Permissions")
    if info.callbacks:
        reasons.append("implements callbacks: " + ", ".join(info.callbacks))
    hookish = (in_ihooks or base_hook is not None) and (declares_perms or bool(info.callbacks))
    is_mock = bool(_MOCK_NAME.search(name) or _MOCK_PATH.search(path))

    if abstract:
        if in_ihooks or base_hook or declares_perms:
            info.kind, info.confidence = "abstract-hook", "high" if in_ihooks else "medium"
            reasons.append("abstract: analysed through the concrete contracts that inherit it")
    elif hookish:
        info.kind, info.confidence = "hook", "high"
    elif declares_perms or (poolkey_cbs and len(poolkey_cbs) >= 1):
        info.kind = "candidate"
        info.confidence = "medium" if declares_perms else "low"
        reasons.append("not in the IHooks inheritance hierarchy: classification is inferred")
    elif delegating:
        info.kind, info.confidence = "candidate", "low"
        reasons.append(
            "delegating proxy (fallback uses DELEGATECALL): could be a hook address whose logic lives in an "
            "implementation contract"
        )
    if is_mock and info.kind in ("hook", "candidate", "abstract-hook"):
        reasons.append("name or path marks it as a mock / test double")
        info.kind = "mock"
    info.reasons = reasons
    return info


def _is_dependency_base(c: dict[str, Any]) -> bool:
    return bool(re.search(r"BaseHook", str(c.get("name")))) or c.get("name") == "IHooks"


def _only_reverts(fn: dict[str, Any]) -> bool:
    stmts = (fn.get("body") or {}).get("statements") or []
    return len(stmts) == 1 and stmts[0].get("nodeType") == "RevertStatement"


def _delegating_fallback(fns: list[dict[str, Any]]) -> bool:
    """A fallback exists and the contract's own code (fallback or an internal helper) delegatecalls."""
    if not any(f.get("kind") == "fallback" and f.get("body") for f in fns):
        return False
    for f in fns:
        if not f.get("body"):
            continue
        for n in _iter(f["body"]):
            if n.get("nodeType") == "YulFunctionCall" and (n.get("functionName") or {}).get("name") == "delegatecall":
                return True
            if n.get("nodeType") == "MemberAccess" and n.get("memberName") == "delegatecall":
                return True
    return False

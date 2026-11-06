"""Index over the solc compact JSON AST.

Builds, for the analysed contract and its linearised bases:
  * contracts, functions, modifiers and state variables with exact source locations;
  * per-function facts: internal calls, external calls (with targets), state reads/writes,
    revert conditions, msg.sender comparisons, timestamp use, PoolManager interactions;
  * transitive closure of facts through internal calls and modifiers.

All locations come from AST `src` byte offsets, so source excerpts are exact.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from app.analyzers.source.bundle import SourceBundle

POOL_MANAGER_METHODS = {
    "take",
    "settle",
    "settleFor",
    "mint",
    "burn",
    "sync",
    "clear",
    "unlock",
    "donate",
    "swap",
    "modifyLiquidity",
    "updateDynamicLPFee",
    "initialize",
    "extsload",
    "exttload",
}
ORACLE_METHODS = {
    "latestRoundData",
    "latestAnswer",
    "getRoundData",
    "getPrice",
    "getPriceUnsafe",
    "getPriceNoOlderThan",
    "consult",
    "observe",
    "getReserves",
    "price",
    "read",
    "peek",
    "getAssetPrice",
    "latestTimestamp",
}
TOKEN_METHODS = {"transfer", "transferFrom", "approve", "balanceOf", "safeTransfer", "safeTransferFrom"}


@dataclass
class Location:
    file: str
    start: int
    length: int
    line_start: int
    line_end: int

    def to_dict(self) -> dict[str, Any]:
        return {"file": self.file, "line_start": self.line_start, "line_end": self.line_end}


@dataclass
class ExternalCall:
    kind: str  # high-level | low-level-call | delegatecall | staticcall | transfer
    member: str
    target_text: str
    target_type: str
    target_state_var: int | None
    target_is_pool_manager: bool
    function_selector: str | None
    in_try: bool
    loc: Location

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "member": self.member,
            "target": self.target_text,
            "target_type": self.target_type,
            "target_is_pool_manager": self.target_is_pool_manager,
            "function_selector": self.function_selector,
            "in_try": self.in_try,
            "location": self.loc.to_dict(),
        }


@dataclass
class RevertSite:
    kind: str  # require | revert | if-revert | assert
    condition: str
    error: str | None
    loc: Location
    referenced_ids: set[int] = field(default_factory=set)
    uses_timestamp: bool = False
    uses_msg_sender: bool = False


@dataclass
class FunctionInfo:
    id: int
    name: str
    contract: str
    kind: str
    visibility: str
    mutability: str
    selector: str | None
    modifiers: list[str]
    modifier_ids: list[int]
    params: list[tuple[str, str]]
    returns: list[str]
    loc: Location
    implemented: bool
    internal_calls: set[int] = field(default_factory=set)
    external_calls: list[ExternalCall] = field(default_factory=list)
    state_reads: set[int] = field(default_factory=set)
    state_writes: set[int] = field(default_factory=set)
    reverts: list[RevertSite] = field(default_factory=list)
    sender_checks: list[tuple[str, Location, set[int]]] = field(default_factory=list)
    uses_timestamp: bool = False
    uses_tx_origin: bool = False
    has_assembly: bool = False
    assembly_ops: set[str] = field(default_factory=set)
    identifiers: set[str] = field(default_factory=set)
    member_names: set[str] = field(default_factory=set)
    numeric_literals: list[str] = field(default_factory=list)
    divisions: int = 0

    @property
    def signature(self) -> str:
        return f"{self.name}({','.join(t for _, t in self.params)})"


@dataclass
class StateVar:
    id: int
    name: str
    contract: str
    type_string: str
    visibility: str
    constant: bool
    immutable: bool
    selector: str | None
    loc: Location
    value_text: str | None


@dataclass
class ModifierInfo:
    id: int
    name: str
    contract: str
    loc: Location
    facts: FunctionInfo  # body facts collected with the same walker


class AstIndex:
    def __init__(self, bundle: SourceBundle) -> None:
        self.bundle = bundle
        self._file_by_index = bundle.file_by_index()
        self._src_bytes = {p: c.encode("utf-8") for p, c in bundle.sources.items()}
        self._line_starts: dict[str, list[int]] = {}
        self.nodes: dict[int, dict[str, Any]] = {}
        self.contracts: dict[int, dict[str, Any]] = {}
        self.functions: dict[int, FunctionInfo] = {}
        self.modifiers: dict[int, ModifierInfo] = {}
        self.state_vars: dict[int, StateVar] = {}
        for _path, out in bundle.output_sources.items():
            ast = out.get("ast")
            if isinstance(ast, dict):
                self._register(ast)
        self.main = self._find_main()
        self.linearized: list[int] = list(self.main.get("linearizedBaseContracts", [])) if self.main else []
        for cid in self.linearized:
            c = self.contracts.get(cid)
            if c:
                self._index_contract(c)

    # ------------------------------------------------------------------ registration
    def _register(self, node: Any) -> None:
        stack = [node]
        while stack:
            n = stack.pop()
            if isinstance(n, dict):
                nid = n.get("id")
                if isinstance(nid, int) and "nodeType" in n:
                    self.nodes[nid] = n
                    if n["nodeType"] == "ContractDefinition":
                        self.contracts[nid] = n
                stack.extend(v for v in n.values() if isinstance(v, (dict, list)))
            elif isinstance(n, list):
                stack.extend(n)

    def _find_main(self) -> dict[str, Any] | None:
        name = self.bundle.contract_name
        cands = [c for c in self.contracts.values() if c.get("name") == name]
        if not cands:
            return None
        path = self.bundle.contract_path
        for c in cands:
            if self._loc(c).file == path:
                return c
        return cands[0]

    # ------------------------------------------------------------------ locations
    def _lines(self, path: str) -> list[int]:
        if path not in self._line_starts:
            data = self._src_bytes.get(path, b"")
            starts = [0]
            for i, b in enumerate(data):
                if b == 10:
                    starts.append(i + 1)
            self._line_starts[path] = starts
        return self._line_starts[path]

    def _line_of(self, path: str, offset: int) -> int:
        starts = self._lines(path)
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= offset:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    def _loc(self, node: dict[str, Any]) -> Location:
        try:
            s, length, f = (int(x) for x in str(node.get("src", "0:0:-1")).split(":"))
        except ValueError:
            s, length, f = 0, 0, -1
        path = self._file_by_index.get(f, "<unknown>")
        return Location(path, s, length, self._line_of(path, s), self._line_of(path, s + max(length - 1, 0)))

    def text(self, node: dict[str, Any] | Location, limit: int = 400) -> str:
        loc = node if isinstance(node, Location) else self._loc(node)
        data = self._src_bytes.get(loc.file, b"")
        t = data[loc.start : loc.start + loc.length].decode("utf-8", "replace")
        t = " ".join(t.split())
        return t if len(t) <= limit else t[: limit - 1] + "…"

    def excerpt(self, loc: Location, max_lines: int = 60) -> dict[str, Any]:
        content = self.bundle.sources.get(loc.file, "")
        lines = content.splitlines()
        start = max(loc.line_start, 1)
        end = min(loc.line_end, start + max_lines - 1, len(lines))
        return {
            "file": loc.file,
            "line_start": start,
            "line_end": end,
            "truncated": loc.line_end > end,
            "code": "\n".join(lines[start - 1 : end]),
        }

    # ------------------------------------------------------------------ indexing
    def _index_contract(self, c: dict[str, Any]) -> None:
        cname = c.get("name", "?")
        for n in c.get("nodes", []):
            nt = n.get("nodeType")
            if nt == "FunctionDefinition":
                self.functions[n["id"]] = self._function(n, cname)
            elif nt == "ModifierDefinition":
                facts = FunctionInfo(
                    id=n["id"],
                    name=n.get("name", ""),
                    contract=cname,
                    kind="modifier",
                    visibility="internal",
                    mutability="",
                    selector=None,
                    modifiers=[],
                    modifier_ids=[],
                    params=[],
                    returns=[],
                    loc=self._loc(n),
                    implemented=bool(n.get("body")),
                )
                if n.get("body"):
                    self._walk(n["body"], facts, in_try=False)
                self.modifiers[n["id"]] = ModifierInfo(n["id"], n.get("name", ""), cname, self._loc(n), facts)
            elif nt == "VariableDeclaration" and n.get("stateVariable"):
                self.state_vars[n["id"]] = StateVar(
                    id=n["id"],
                    name=n.get("name", ""),
                    contract=cname,
                    type_string=(n.get("typeDescriptions") or {}).get("typeString", ""),
                    visibility=n.get("visibility", ""),
                    constant=bool(n.get("constant")),
                    immutable=n.get("mutability") == "immutable",
                    selector=("0x" + n["functionSelector"]) if n.get("functionSelector") else None,
                    loc=self._loc(n),
                    value_text=self.text(n["value"]) if n.get("value") else None,
                )

    def _function(self, n: dict[str, Any], cname: str) -> FunctionInfo:
        params = [
            (p.get("name", ""), (p.get("typeDescriptions") or {}).get("typeString", ""))
            for p in (n.get("parameters") or {}).get("parameters", [])
        ]
        rets = [
            (p.get("typeDescriptions") or {}).get("typeString", "")
            for p in (n.get("returnParameters") or {}).get("parameters", [])
        ]
        mods, mod_ids = [], []
        for m in n.get("modifiers", []):
            mn = m.get("modifierName") or {}
            mods.append(mn.get("name") or mn.get("namePath") or "")
            if isinstance(mn.get("referencedDeclaration"), int):
                mod_ids.append(mn["referencedDeclaration"])
        fi = FunctionInfo(
            id=n["id"],
            name=n.get("name") or n.get("kind", ""),
            contract=cname,
            kind=n.get("kind", "function"),
            visibility=n.get("visibility", ""),
            mutability=n.get("stateMutability", ""),
            selector=("0x" + n["functionSelector"]) if n.get("functionSelector") else None,
            modifiers=mods,
            modifier_ids=mod_ids,
            params=params,
            returns=rets,
            loc=self._loc(n),
            implemented=bool(n.get("implemented", n.get("body") is not None)),
        )
        if n.get("body"):
            self._walk(n["body"], fi, in_try=False)
        return fi

    def _ref_state_var(self, node: dict[str, Any]) -> int | None:
        ref = node.get("referencedDeclaration")
        if isinstance(ref, int):
            d = self.nodes.get(ref)
            if d and d.get("nodeType") == "VariableDeclaration" and d.get("stateVariable"):
                return ref
        return None

    def _base_state_var(self, expr: dict[str, Any]) -> int | None:
        """State variable at the root of an expression such as `oracle`, `IFoo(oracle)`, `cfg.oracle`."""
        e = expr
        for _ in range(6):
            nt = e.get("nodeType")
            if nt == "Identifier":
                return self._ref_state_var(e)
            if nt == "FunctionCall" and e.get("kind") == "typeConversion" and e.get("arguments"):
                e = e["arguments"][0]
            elif nt in ("MemberAccess", "IndexAccess"):
                e = e.get("expression") or e.get("baseExpression") or {}
            else:
                return None
        return None

    @staticmethod
    def _is_msg_sender(n: dict[str, Any]) -> bool:
        return (
            n.get("nodeType") == "MemberAccess"
            and n.get("memberName") == "sender"
            and (n.get("expression") or {}).get("name") == "msg"
        )

    def _walk(self, node: Any, fi: FunctionInfo, in_try: bool) -> None:
        if isinstance(node, list):
            for x in node:
                self._walk(x, fi, in_try)
            return
        if not isinstance(node, dict):
            return
        nt = node.get("nodeType")

        if nt == "Identifier":
            fi.identifiers.add(node.get("name", ""))
            sv = self._ref_state_var(node)
            if sv is not None:
                fi.state_reads.add(sv)
        elif nt == "MemberAccess":
            fi.member_names.add(node.get("memberName", ""))
            exp = node.get("expression") or {}
            if exp.get("name") == "block" and node.get("memberName") == "timestamp":
                fi.uses_timestamp = True
            if exp.get("name") == "tx" and node.get("memberName") == "origin":
                fi.uses_tx_origin = True
        elif nt == "Literal" and node.get("kind") == "number":
            fi.numeric_literals.append(str(node.get("value")))
        elif nt == "Assignment":
            lhs = node.get("leftHandSide") or {}
            sv = self._base_state_var(lhs)
            if sv is not None:
                fi.state_writes.add(sv)
        elif nt == "UnaryOperation" and node.get("operator") in ("++", "--", "delete"):
            sv = self._base_state_var(node.get("subExpression") or {})
            if sv is not None:
                fi.state_writes.add(sv)
        elif nt == "BinaryOperation":
            if node.get("operator") == "/":
                fi.divisions += 1
            le, re_ = node.get("leftExpression") or {}, node.get("rightExpression") or {}
            if node.get("operator") in ("==", "!=") and (self._is_msg_sender(le) or self._is_msg_sender(re_)):
                other = re_ if self._is_msg_sender(le) else le
                refs = self._collect_refs(other)
                fi.sender_checks.append((self.text(node), self._loc(node), refs))
        elif nt == "InlineAssembly":
            fi.has_assembly = True
            self._yul_ops(node.get("AST"), fi.assembly_ops)
        elif nt == "TryStatement":
            self._walk(node.get("externalCall"), fi, True)
            for c in node.get("clauses", []):
                self._walk(c, fi, in_try)
            return
        elif nt == "RevertStatement":
            call = node.get("errorCall") or {}
            err = self.text(call.get("expression") or {}, 120)
            fi.reverts.append(RevertSite("revert", "", err, self._loc(node)))
        elif nt == "IfStatement":
            body = node.get("trueBody")
            if self._contains_revert(body):
                cond = node.get("condition") or {}
                site = RevertSite(
                    "if-revert",
                    self.text(cond, 300),
                    self._revert_error_name(body),
                    self._loc(node),
                    referenced_ids=self._collect_refs(cond),
                    uses_timestamp=self._mentions(cond, "timestamp"),
                    uses_msg_sender=self._mentions_sender(cond),
                )
                fi.reverts.append(site)
                if site.uses_msg_sender:
                    fi.sender_checks.append((site.condition, site.loc, site.referenced_ids))
        elif nt == "FunctionCall":
            self._function_call(node, fi, in_try)

        for k, v in node.items():
            if k in ("typeDescriptions", "src", "id", "nodeType"):
                continue
            if isinstance(v, (dict, list)):
                self._walk(v, fi, in_try)

    def _function_call(self, node: dict[str, Any], fi: FunctionInfo, in_try: bool) -> None:
        expr = node.get("expression") or {}
        kind = node.get("kind")
        ent = expr.get("nodeType")
        if kind != "functionCall":
            return
        if ent == "Identifier":
            name = expr.get("name")
            if name in ("require", "assert"):
                args = node.get("arguments") or []
                cond = args[0] if args else {}
                err = None
                if len(args) > 1:
                    err = self.text(args[1], 120)
                site = RevertSite(
                    name or "require",
                    self.text(cond, 300),
                    err,
                    self._loc(node),
                    referenced_ids=self._collect_refs(cond),
                    uses_timestamp=self._mentions(cond, "timestamp"),
                    uses_msg_sender=self._mentions_sender(cond),
                )
                fi.reverts.append(site)
                if site.uses_msg_sender:
                    fi.sender_checks.append((site.condition, site.loc, site.referenced_ids))
                return
            if name == "revert":
                fi.reverts.append(RevertSite("revert", "", None, self._loc(node)))
                return
            ref = expr.get("referencedDeclaration")
            if isinstance(ref, int) and (self.nodes.get(ref) or {}).get("nodeType") == "FunctionDefinition":
                fi.internal_calls.add(ref)
            return
        if ent != "MemberAccess":
            return
        member = expr.get("memberName", "")
        base = expr.get("expression") or {}
        base_type = (base.get("typeDescriptions") or {}).get("typeString", "")
        ref = expr.get("referencedDeclaration")
        ref_node = self.nodes.get(ref) if isinstance(ref, int) else None
        # super.f() / library calls / this.f()
        if base.get("name") == "super" and isinstance(ref, int):
            fi.internal_calls.add(ref)
            return
        if base_type.startswith("type(library") or base_type.startswith("library "):
            if ref_node and isinstance(ref, int) and ref_node.get("nodeType") == "FunctionDefinition":
                fi.internal_calls.add(ref)
            # Library wrappers around PoolManager calls still count as PoolManager interaction.
            if member in POOL_MANAGER_METHODS:
                fi.member_names.add(member)
            return
        is_address = base_type.startswith("address")
        if is_address and member in ("call", "delegatecall", "staticcall"):
            kindname = {"call": "low-level-call", "delegatecall": "delegatecall", "staticcall": "staticcall"}[member]
        elif is_address and member in ("transfer", "send"):
            kindname = "transfer"
        elif base_type.startswith("contract ") or base_type.startswith("type(contract"):
            if base.get("name") == "this" and isinstance(ref, int):
                fi.internal_calls.add(ref)
            kindname = "high-level"
        else:
            return
        target_sv = self._base_state_var(base)
        sv_name = str((self.nodes.get(target_sv) or {}).get("name", "")).lower() if target_sv is not None else ""
        is_pm = "PoolManager" in base_type or "poolmanager" in sv_name
        sel = None
        if ref_node and ref_node.get("functionSelector"):
            sel = "0x" + ref_node["functionSelector"]
        fi.external_calls.append(
            ExternalCall(
                kind=kindname,
                member=member,
                target_text=self.text(base, 160),
                target_type=base_type,
                target_state_var=target_sv,
                target_is_pool_manager=is_pm,
                function_selector=sel,
                in_try=in_try,
                loc=self._loc(node),
            )
        )

    def _collect_refs(self, node: Any) -> set[int]:
        out: set[int] = set()
        for n in _iter(node):
            ref = n.get("referencedDeclaration")
            if isinstance(ref, int):
                out.add(ref)
        return out

    def _mentions(self, node: Any, member: str) -> bool:
        return any(n.get("memberName") == member or n.get("name") == member for n in _iter(node))

    def _mentions_sender(self, node: Any) -> bool:
        return any(self._is_msg_sender(n) for n in _iter(node))

    def _contains_revert(self, node: Any) -> bool:
        for n in _iter(node):
            if n.get("nodeType") == "RevertStatement":
                return True
            if n.get("nodeType") == "FunctionCall" and (n.get("expression") or {}).get("name") == "revert":
                return True
        return False

    def _revert_error_name(self, node: Any) -> str | None:
        for n in _iter(node):
            if n.get("nodeType") == "RevertStatement":
                return self.text((n.get("errorCall") or {}).get("expression") or {}, 120)
        return None

    def _yul_ops(self, node: Any, out: set[str]) -> None:
        for n in _iter(node):
            if n.get("nodeType") == "YulFunctionCall":
                name = (n.get("functionName") or {}).get("name")
                if name:
                    out.add(name)

    # ------------------------------------------------------------------ queries
    def resolve(self, name: str) -> FunctionInfo | None:
        """Most-derived implemented function with this name in the linearised hierarchy."""
        for cid in self.linearized:
            for fi in self.functions.values():
                if fi.name == name and fi.contract == self.contracts[cid].get("name") and fi.implemented:
                    return fi
        return None

    def public_functions(self) -> list[FunctionInfo]:
        """Externally callable functions of the main contract (most-derived per selector)."""
        seen: dict[str, FunctionInfo] = {}
        for cid in self.linearized:
            cname = self.contracts[cid].get("name")
            for fi in self.functions.values():
                if fi.contract != cname or fi.visibility not in ("public", "external") or fi.kind != "function":
                    continue
                key = fi.selector or fi.signature
                if key not in seen:
                    seen[key] = fi
        return list(seen.values())

    def special_functions(self) -> list[FunctionInfo]:
        return [f for f in self.functions.values() if f.kind in ("fallback", "receive", "constructor")]

    def closure(self, fi: FunctionInfo) -> list[FunctionInfo]:
        """The function, the modifiers it uses, and everything reachable through internal calls."""
        out: list[FunctionInfo] = []
        seen: set[int] = set()
        stack: list[FunctionInfo] = [fi]
        while stack:
            f = stack.pop()
            if f.id in seen:
                continue
            seen.add(f.id)
            out.append(f)
            for mid in f.modifier_ids:
                m = self.modifiers.get(mid)
                if m and m.facts.id not in seen:
                    stack.append(m.facts)
            for cid in f.internal_calls:
                g = self.functions.get(cid)
                if g is None:
                    # Could be a function of a library or a contract outside the hierarchy.
                    node = self.nodes.get(cid)
                    if node and node.get("nodeType") == "FunctionDefinition":
                        g = self._function(node, "<external-def>")
                        self.functions[cid] = g
                if g is not None and g.id not in seen:
                    stack.append(g)
        return out

    def state_var(self, sid: int) -> StateVar | None:
        return self.state_vars.get(sid)


def _iter(node: Any) -> Iterator[dict[str, Any]]:
    stack = [node]
    while stack:
        n = stack.pop()
        if isinstance(n, dict):
            yield n
            stack.extend(v for k, v in n.items() if isinstance(v, (dict, list)) and k != "typeDescriptions")
        elif isinstance(n, list):
            stack.extend(n)

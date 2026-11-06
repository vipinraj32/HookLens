"""Parse `forge test --json -vvvv` traces into compact, decoded call trees.

The Execution arena is a flat list of call nodes in execution order. Cheatcode and console
calls are pruned. Each scenario step is recorded by the harness through a `vm.writeLine`
cheatcode call carrying the step JSON, so the calls executed for a step are exactly the
top-level calls between the previous step record and this one.
"""

from __future__ import annotations

import json
from typing import Any

from eth_abi import decode as abi_decode

from app.services.evm import keccak
from app.simulation.decode import Registry, decode_revert, function_label

CHEATCODE = "0x7109709ecfa91a80626ff3989d68f67f5b1dd12d"
CONSOLE = "0x000000000000000000636f6e736f6c652e6c6f67"
WRITE_LINE = "0x" + keccak(b"writeLine(string,string)").hex()[:8]
MAX_NODES = 2500
MAX_DATA_HEX = 266


class TraceParseError(Exception):
    pass


def _step_from_write_line(data: str) -> str | None:
    try:
        _path, line = abi_decode(["string", "string"], bytes.fromhex(data[10:]))
        return str(json.loads(line).get("name"))
    except Exception:
        return None


def parse_test_result(test: dict[str, Any], reg: Registry, labels: dict[str, str]) -> dict[str, Any]:
    traces = test.get("traces") or []
    arenas = {kind: arena.get("arena", []) for kind, arena in traces}
    nodes = arenas.get("Execution")
    if nodes is None:
        raise TraceParseError("No Execution trace in forge output (was -vvvv passed?).")
    labeled = {k.lower(): v for k, v in (test.get("labeled_addresses") or {}).items()}
    labeled.update({k.lower(): v for k, v in labels.items()})

    by_idx = {n["idx"]: n for n in nodes}
    keep: dict[int, dict[str, Any]] = {}
    pruned = 0
    for n in nodes:
        tr = n["trace"]
        addr = (tr.get("address") or "").lower()
        if addr in (CHEATCODE, CONSOLE):
            pruned += 1
            continue
        if len(keep) >= MAX_NODES:
            continue
        sel = function_label(tr.get("data"), reg)
        rec: dict[str, Any] = {
            "idx": n["idx"],
            "parent": n["parent"],
            "depth": tr.get("depth"),
            "kind": tr.get("kind"),
            "caller": tr.get("caller"),
            "caller_label": labeled.get((tr.get("caller") or "").lower()),
            "address": tr.get("address"),
            "label": labeled.get(addr),
            "selector": sel["selector"],
            "function": sel["function"],
            "value": tr.get("value"),
            "success": bool(tr.get("success")),
            "status": tr.get("status"),
            "gas_used": tr.get("gas_used"),
            "data": (tr.get("data") or "")[:MAX_DATA_HEX],
            "data_truncated": len(tr.get("data") or "") > MAX_DATA_HEX,
            "log_count": len(n.get("logs") or []),
        }
        if not rec["success"]:
            rec["revert"] = decode_revert(tr.get("output"), reg)
        keep[n["idx"]] = rec
    for rec in keep.values():
        rec["children"] = [c for c in by_idx[rec["idx"]].get("children", []) if c in keep]

    # Segment top-level calls by step.
    root = nodes[0] if nodes else None
    steps: dict[str, list[int]] = {}
    pending: list[int] = []
    if root is not None:
        for c in root.get("children", []):
            tr = by_idx[c]["trace"]
            if (tr.get("address") or "").lower() == CHEATCODE:
                if (tr.get("data") or "").startswith(WRITE_LINE):
                    name = _step_from_write_line(tr["data"])
                    if name:
                        steps.setdefault(name, []).extend(i for i in pending if i in keep)
                        pending = []
                continue
            if c in keep:
                pending.append(c)
    root_rec = keep.get(root["idx"]) if root else None
    return {
        "format": "hooklens-trace/1",
        "root": root_rec["idx"] if root_rec else None,
        "nodes": list(keep.values()),
        "steps": steps,
        "unattributed": pending,
        "pruned_cheatcode_calls": pruned,
        "total_nodes": len(nodes),
        "truncated": len(nodes) - pruned > MAX_NODES,
        "setup_nodes": len(arenas.get("Setup") or []),
    }


def first_revert_chain(trace: dict[str, Any], node_ids: list[int]) -> list[dict[str, Any]]:
    """Path from a step's top-level call down to the deepest reverting frame."""
    nodes = {n["idx"]: n for n in trace.get("nodes", [])}

    def first_failure(idx: int) -> dict[str, Any] | None:
        # Actors catch reverts (tryCall), so the failing frame can sit below a successful one.
        n = nodes.get(idx)
        if n is None:
            return None
        if not n["success"]:
            return n
        for c in n.get("children", []):
            hit = first_failure(c)
            if hit is not None:
                return hit
        return None

    for top in node_ids:
        n = first_failure(top)
        if n is None:
            continue
        chain = [n]
        while True:
            kids = [nodes[c] for c in n.get("children", []) if c in nodes and not nodes[c]["success"]]
            if not kids:
                break
            n = kids[-1]
            chain.append(n)
        return [
            {
                "idx": x["idx"],
                "address": x["address"],
                "label": x.get("label"),
                "function": x.get("function"),
                "selector": x.get("selector"),
                "revert": x.get("revert"),
            }
            for x in chain
        ]
    return []

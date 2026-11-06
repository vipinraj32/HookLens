"""Solidity `pragma solidity` version ranges (npm-semver subset used by solc)."""

from __future__ import annotations

import re

Version = tuple[int, int, int]

_PRAGMA_RE = re.compile(r"pragma\s+solidity\s+([^;]+);")
_COMP_RE = re.compile(r"(\^|~|>=|<=|>|<|=)?\s*v?(\d+)(?:\.(\d+|x|\*))?(?:\.(\d+|x|\*))?")


def parse_version(v: str) -> Version:
    a, b, c = (int(x) for x in v.split("+")[0].split(".")[:3])
    return (a, b, c)


def fmt(v: Version) -> str:
    return ".".join(str(x) for x in v)


def pragmas(source: str) -> list[str]:
    return [m.group(1).strip() for m in _PRAGMA_RE.finditer(source)]


def _comparators(expr: str) -> list[tuple[str, Version, int]]:
    """Returns (op, version, precision) where precision = number of explicit components."""
    out = []
    pos = 0
    expr = expr.strip()
    while pos < len(expr):
        if expr[pos].isspace():
            pos += 1
            continue
        m = _COMP_RE.match(expr, pos)
        if not m or m.end() == pos:
            raise ValueError(f"unsupported version expression: {expr!r}")
        op = m.group(1) or "="
        parts = [m.group(2), m.group(3), m.group(4)]
        precision = sum(1 for p in parts if p is not None and p not in ("x", "*"))
        nums = [int(p) if p is not None and p not in ("x", "*") else 0 for p in parts]
        out.append((op, (nums[0], nums[1], nums[2]), precision))
        pos = m.end()
    return out


def _match_one(v: Version, op: str, t: Version, precision: int) -> bool:
    if op == "^":
        if v < t:
            return False
        if t[0] > 0:
            return v[0] == t[0]
        if t[1] > 0 or precision < 3:
            return v[0] == 0 and v[1] == t[1]
        return v == t
    if op == "~":
        if v < t:
            return False
        return v[:2] == t[:2] if precision >= 2 else v[0] == t[0]
    if op == "=":
        if precision == 3:
            return v == t
        return v[:precision] == t[:precision]
    return {">=": v >= t, "<=": v <= t, ">": v > t, "<": v < t}[op]


def satisfies(version: Version, expr: str) -> bool:
    for alt in expr.split("||"):
        comps = _comparators(alt)
        if all(_match_one(version, op, t, p) for op, t, p in comps):
            return True
    return False


def best_version(candidates: list[Version], exprs: list[str]) -> Version | None:
    ok = [v for v in candidates if all(satisfies(v, e) for e in exprs)]
    return max(ok) if ok else None

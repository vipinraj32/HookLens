"""Selector and revert decoding for simulation traces.

Signatures come from the compiled Foundry artifacts (v4-core, v4-periphery, harness, fixtures)
and, when available, the analysed contract's verified ABI. Unknown selectors stay as raw hex:
nothing is guessed.
"""

from __future__ import annotations

import json
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

from eth_abi import decode as abi_decode

from app.config import get_settings
from app.services.evm import keccak

ERROR_STRING = "0x08c379a0"
PANIC = "0x4e487b71"
WRAPPED_ERROR = "0x90bfb865"  # CustomRevert.WrappedError(address,bytes4,bytes,bytes)

PANIC_CODES = {
    0x00: "generic compiler panic",
    0x01: "assert(false)",
    0x11: "arithmetic overflow/underflow",
    0x12: "division or modulo by zero",
    0x21: "invalid enum value",
    0x22: "invalid storage byte array",
    0x31: "pop on empty array",
    0x32: "array index out of bounds",
    0x41: "out of memory",
    0x51: "call to zero-initialized function",
}


def _canonical_type(p: dict[str, Any]) -> str:
    t = p["type"]
    if t.startswith("tuple"):
        inner = ",".join(_canonical_type(c) for c in p.get("components", []))
        return f"({inner}){t[5:]}"
    return t


def _abi_items(abi: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    fns: dict[str, dict[str, Any]] = {}
    errs: dict[str, dict[str, Any]] = {}
    for item in abi or []:
        kind = item.get("type")
        if kind not in ("function", "error"):
            continue
        types = [_canonical_type(p) for p in item.get("inputs", [])]
        sig = f"{item['name']}({','.join(types)})"
        sel = "0x" + keccak(sig.encode()).hex()[:8]
        entry = {
            "signature": sig,
            "name": item["name"],
            "types": types,
            "names": [p.get("name") or f"arg{i}" for i, p in enumerate(item.get("inputs", []))],
        }
        (fns if kind == "function" else errs)[sel] = entry
    return fns, errs


class Registry:
    def __init__(self) -> None:
        self.functions: dict[str, dict[str, Any]] = {}
        self.errors: dict[str, dict[str, Any]] = {}

    def add_abi(self, abi: list[dict[str, Any]] | None) -> None:
        if not abi:
            return
        f, e = _abi_items(abi)
        for k, v in f.items():
            self.functions.setdefault(k, v)
        for k, v in e.items():
            self.errors.setdefault(k, v)

    def copy(self) -> Registry:
        r = Registry()
        r.functions = dict(self.functions)
        r.errors = dict(self.errors)
        return r


_lock = threading.Lock()


@lru_cache(maxsize=1)
def _artifact_registry(out_dir: str) -> Registry:
    reg = Registry()
    root = Path(out_dir)
    if not root.exists():
        return reg
    for p in sorted(root.glob("*/*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        reg.add_abi(data.get("abi"))
    return reg


def registry(extra_abi: list[dict[str, Any]] | None = None) -> Registry:
    with _lock:
        base = _artifact_registry(str(get_settings().contracts_dir / "out"))
    reg = base.copy()
    if extra_abi:
        # The analysed contract's own ABI takes precedence for its selectors.
        f, e = _abi_items(extra_abi)
        reg.functions.update(f)
        reg.errors.update(e)
    return reg


def _fmt(v: Any) -> Any:
    if isinstance(v, bytes):
        return "0x" + v.hex()
    if isinstance(v, (list, tuple)):
        return [_fmt(x) for x in v]
    if isinstance(v, int) and abs(v) > 2**53:
        return str(v)
    return v


def _printable(b: bytes) -> str | None:
    try:
        s = b.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return s if s and all(c.isprintable() for c in s) else None


def decode_revert(data: str | None, reg: Registry, depth: int = 0) -> dict[str, Any] | None:
    """Decode revert data into {kind, selector, name, args, message, inner?}."""
    if not data or data in ("0x", ""):
        return {"kind": "empty", "message": "Reverted without data"} if data is not None else None
    raw = bytes.fromhex(data[2:] if data.startswith("0x") else data)
    if len(raw) < 4:
        return {"kind": "raw", "data": data, "message": "Revert data shorter than a selector"}
    sel = "0x" + raw[:4].hex()
    body = raw[4:]
    try:
        if sel == ERROR_STRING:
            (msg,) = abi_decode(["string"], body)
            return {"kind": "error_string", "selector": sel, "name": "Error", "message": msg}
        if sel == PANIC:
            (code,) = abi_decode(["uint256"], body)
            return {
                "kind": "panic",
                "selector": sel,
                "name": "Panic",
                "code": code,
                "message": f"Panic(0x{code:02x}): {PANIC_CODES.get(code, 'unknown panic code')}",
            }
        if sel == WRAPPED_ERROR:
            target, fsel, reason, details = abi_decode(["address", "bytes4", "bytes", "bytes"], body)
            inner = decode_revert("0x" + reason.hex(), reg, depth + 1) if depth < 4 else None
            details_dec = decode_revert("0x" + details.hex(), reg, depth + 1) if details and depth < 4 else None
            fn = reg.functions.get("0x" + fsel.hex())
            where = f"{fn['name'] if fn else '0x' + fsel.hex()} on {target}"
            return {
                "kind": "wrapped",
                "selector": sel,
                "name": "WrappedError",
                "target": target,
                "function_selector": "0x" + fsel.hex(),
                "function": fn["signature"] if fn else None,
                "inner": inner,
                "details": details_dec,
                "message": f"Hook call {where} reverted: " + ((inner or {}).get("message") or "no reason"),
            }
    except Exception:
        return {"kind": "raw", "selector": sel, "data": data, "message": f"Undecodable revert with selector {sel}"}
    err = reg.errors.get(sel)
    if err:
        try:
            vals = abi_decode(err["types"], body) if err["types"] else ()
            args = {n: _fmt(v) for n, v in zip(err["names"], vals, strict=False)}
        except Exception:
            args = {"_raw": "0x" + body.hex()}
        rendered = ", ".join(f"{k}={v}" for k, v in args.items())
        return {
            "kind": "custom",
            "selector": sel,
            "name": err["name"],
            "signature": err["signature"],
            "args": args,
            "message": f"{err['name']}({rendered})",
        }
    text = _printable(raw)
    if text:
        return {"kind": "raw_string", "message": text}
    return {"kind": "unknown", "selector": sel, "data": data[:202], "message": f"Unknown custom error {sel}"}


def function_label(data: str | None, reg: Registry) -> dict[str, Any]:
    if not data or len(data) < 10:
        return {"selector": None, "function": None}
    sel = data[:10].lower()
    fn = reg.functions.get(sel)
    return {"selector": sel, "function": fn["signature"] if fn else None}

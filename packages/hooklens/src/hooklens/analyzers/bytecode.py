"""Runtime bytecode analysis that does not require source code.

Everything here is a property of the deployed bytes: the opcode inventory, the function
selector dispatcher, embedded PUSH20 constants, CBOR compiler metadata and well-known proxy
patterns. Selector extraction is a heuristic over the solc dispatcher and is labelled as such.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hooklens.evm import keccak, selector

# opcode -> (name, immediate bytes)
_OPS: dict[int, str] = {
    0x00: "STOP",
    0x01: "ADD",
    0x02: "MUL",
    0x03: "SUB",
    0x04: "DIV",
    0x05: "SDIV",
    0x06: "MOD",
    0x07: "SMOD",
    0x08: "ADDMOD",
    0x09: "MULMOD",
    0x0A: "EXP",
    0x0B: "SIGNEXTEND",
    0x10: "LT",
    0x11: "GT",
    0x12: "SLT",
    0x13: "SGT",
    0x14: "EQ",
    0x15: "ISZERO",
    0x16: "AND",
    0x17: "OR",
    0x18: "XOR",
    0x19: "NOT",
    0x1A: "BYTE",
    0x1B: "SHL",
    0x1C: "SHR",
    0x1D: "SAR",
    0x20: "KECCAK256",
    0x30: "ADDRESS",
    0x31: "BALANCE",
    0x32: "ORIGIN",
    0x33: "CALLER",
    0x34: "CALLVALUE",
    0x35: "CALLDATALOAD",
    0x36: "CALLDATASIZE",
    0x37: "CALLDATACOPY",
    0x38: "CODESIZE",
    0x39: "CODECOPY",
    0x3A: "GASPRICE",
    0x3B: "EXTCODESIZE",
    0x3C: "EXTCODECOPY",
    0x3D: "RETURNDATASIZE",
    0x3E: "RETURNDATACOPY",
    0x3F: "EXTCODEHASH",
    0x40: "BLOCKHASH",
    0x41: "COINBASE",
    0x42: "TIMESTAMP",
    0x43: "NUMBER",
    0x44: "PREVRANDAO",
    0x45: "GASLIMIT",
    0x46: "CHAINID",
    0x47: "SELFBALANCE",
    0x48: "BASEFEE",
    0x49: "BLOBHASH",
    0x4A: "BLOBBASEFEE",
    0x50: "POP",
    0x51: "MLOAD",
    0x52: "MSTORE",
    0x53: "MSTORE8",
    0x54: "SLOAD",
    0x55: "SSTORE",
    0x56: "JUMP",
    0x57: "JUMPI",
    0x58: "PC",
    0x59: "MSIZE",
    0x5A: "GAS",
    0x5B: "JUMPDEST",
    0x5C: "TLOAD",
    0x5D: "TSTORE",
    0x5E: "MCOPY",
    0x5F: "PUSH0",
    0xF0: "CREATE",
    0xF1: "CALL",
    0xF2: "CALLCODE",
    0xF3: "RETURN",
    0xF4: "DELEGATECALL",
    0xF5: "CREATE2",
    0xFA: "STATICCALL",
    0xFD: "REVERT",
    0xFE: "INVALID",
    0xFF: "SELFDESTRUCT",
}
for _i in range(1, 33):
    _OPS[0x5F + _i] = f"PUSH{_i}"
for _i in range(1, 17):
    _OPS[0x7F + _i] = f"DUP{_i}"
    _OPS[0x8F + _i] = f"SWAP{_i}"
for _i in range(5):
    _OPS[0xA0 + _i] = f"LOG{_i}"

INTERESTING_OPS = (
    "CALL",
    "STATICCALL",
    "DELEGATECALL",
    "CALLCODE",
    "SELFDESTRUCT",
    "CREATE",
    "CREATE2",
    "SSTORE",
    "TSTORE",
    "TLOAD",
    "TIMESTAMP",
    "ORIGIN",
    "BALANCE",
    "EXTCODESIZE",
)

EIP1167_PREFIX = bytes.fromhex("363d3d373d3d3d363d73")
EIP1167_SUFFIX = bytes.fromhex("5af43d82803e903d91602b57fd5bf3")

# Well-known function signatures used for bytecode-only heuristics. Presence of a selector in
# the dispatcher indicates the function is externally callable; it says nothing about guards.
KNOWN_SIGNATURES: dict[str, str] = {
    sig: selector(sig)
    for sig in (
        "owner()",
        "transferOwnership(address)",
        "renounceOwnership()",
        "acceptOwnership()",
        "pendingOwner()",
        "pause()",
        "unpause()",
        "paused()",
        "setPaused(bool)",
        "upgradeTo(address)",
        "upgradeToAndCall(address,bytes)",
        "implementation()",
        "admin()",
        "changeAdmin(address)",
        "proxiableUUID()",
        "grantRole(bytes32,address)",
        "revokeRole(bytes32,address)",
        "hasRole(bytes32,address)",
        "setFee(uint24)",
        "setFee(uint256)",
        "setLPFee(uint24)",
        "setDynamicFee(uint24)",
        "setMaxFee(uint24)",
        "setOracle(address)",
        "setPriceFeed(address)",
        "latestRoundData()",
        "latestAnswer()",
        "getHookPermissions()",
        "poolManager()",
        "rescue(address,address,uint256)",
        "sweep(address,address)",
        "withdraw(address,uint256)",
        "setAllowlist(address,bool)",
        "setBlacklist(address,bool)",
    )
}
SELECTOR_TO_SIGNATURE = {v: k for k, v in KNOWN_SIGNATURES.items()}


@dataclass
class Instruction:
    pc: int
    op: str
    arg: bytes | None = None


@dataclass
class BytecodeFacts:
    code_size: int
    opcode_counts: dict[str, int]
    selectors: list[str]
    known_functions: list[str]
    push20_constants: list[str]
    metadata: dict[str, Any] | None
    minimal_proxy_target: str | None
    has_delegatecall: bool
    has_selfdestruct: bool
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code_size": self.code_size,
            "opcode_counts": self.opcode_counts,
            "selectors": self.selectors,
            "known_functions": self.known_functions,
            "push20_constants": self.push20_constants,
            "metadata": self.metadata,
            "minimal_proxy_target": self.minimal_proxy_target,
            "has_delegatecall": self.has_delegatecall,
            "has_selfdestruct": self.has_selfdestruct,
            "notes": self.notes,
        }


def split_metadata(code: bytes) -> tuple[bytes, bytes | None]:
    """Split trailing CBOR metadata (solc appends `cbor || len(cbor) as uint16`)."""
    if len(code) < 4:
        return code, None
    length = int.from_bytes(code[-2:], "big")
    if length == 0 or length + 2 > len(code):
        return code, None
    cbor = code[-2 - length : -2]
    if not cbor or (cbor[0] & 0xE0) != 0xA0:  # must start with a CBOR map
        return code, None
    return code[: -2 - length], cbor


def _cbor_decode(data: bytes, i: int = 0) -> tuple[Any, int]:
    """Minimal CBOR decoder sufficient for solc metadata (maps, text, bytes, uints, bools)."""
    ib = data[i]
    major, info = ib >> 5, ib & 0x1F
    i += 1

    def _len(info: int, i: int) -> tuple[int, int]:
        if info < 24:
            return info, i
        n = {24: 1, 25: 2, 26: 4, 27: 8}[info]
        return int.from_bytes(data[i : i + n], "big"), i + n

    if major == 0:
        v, i = _len(info, i)
        return v, i
    if major in (2, 3):
        n, i = _len(info, i)
        raw = data[i : i + n]
        return (raw if major == 2 else raw.decode("utf-8", "replace")), i + n
    if major == 4:
        n, i = _len(info, i)
        arr = []
        for _ in range(n):
            v, i = _cbor_decode(data, i)
            arr.append(v)
        return arr, i
    if major == 5:
        n, i = _len(info, i)
        out: dict[Any, Any] = {}
        for _ in range(n):
            k, i = _cbor_decode(data, i)
            v, i = _cbor_decode(data, i)
            out[k] = v
        return out, i
    if major == 7:
        return {20: False, 21: True, 22: None}.get(info), i
    raise ValueError("unsupported CBOR item")


def decode_metadata(cbor: bytes | None) -> dict[str, Any] | None:
    if not cbor:
        return None
    try:
        raw, _ = _cbor_decode(cbor)
    except (ValueError, IndexError, KeyError):
        return {"undecodable": True}
    if not isinstance(raw, dict):
        return {"undecodable": True}
    out: dict[str, Any] = {}
    for k, v in raw.items():
        if k == "solc" and isinstance(v, bytes) and len(v) == 3:
            out["solc"] = f"{v[0]}.{v[1]}.{v[2]}"
        elif isinstance(v, bytes):
            out[str(k)] = "0x" + v.hex()
        else:
            out[str(k)] = v
    return out


def disassemble(code: bytes) -> list[Instruction]:
    out: list[Instruction] = []
    i = 0
    n = len(code)
    while i < n:
        b = code[i]
        name = _OPS.get(b, f"UNKNOWN_0x{b:02x}")
        if 0x60 <= b <= 0x7F:
            size = b - 0x5F
            out.append(Instruction(i, name, code[i + 1 : i + 1 + size]))
            i += 1 + size
        else:
            out.append(Instruction(i, name))
            i += 1
    return out


def analyze_bytecode(code: bytes) -> BytecodeFacts:
    body, cbor = split_metadata(code)
    ins = disassemble(body)
    counts: dict[str, int] = {}
    for x in ins:
        if x.op in INTERESTING_OPS:
            counts[x.op] = counts.get(x.op, 0) + 1

    sels: set[str] = set()
    for idx, x in enumerate(ins):
        if x.op == "PUSH4" and x.arg is not None:
            window = [y.op for y in ins[idx + 1 : idx + 4]]
            if (
                "EQ" in window
                or ("GT" in window or "LT" in window)
                and "JUMPI" in [y.op for y in ins[idx + 1 : idx + 6]]
            ):
                sels.add("0x" + x.arg.hex())

    p20: set[str] = set()
    for x in ins:
        if x.op == "PUSH20" and x.arg is not None:
            v = int.from_bytes(x.arg, "big")
            if v not in (0, (1 << 160) - 1) and x.arg.count(0) < 16:
                p20.add("0x" + x.arg.hex())

    minimal_target = None
    if code.startswith(EIP1167_PREFIX) and EIP1167_SUFFIX in code[30:]:
        minimal_target = "0x" + code[10:30].hex()

    known = sorted(SELECTOR_TO_SIGNATURE[s] for s in sels if s in SELECTOR_TO_SIGNATURE)
    notes = ["Selectors are extracted heuristically from the solc dispatcher pattern."]
    if counts.get("DELEGATECALL"):
        notes.append("DELEGATECALL present: code executed may come from another contract.")
    return BytecodeFacts(
        code_size=len(code),
        opcode_counts=counts,
        selectors=sorted(sels),
        known_functions=known,
        push20_constants=sorted(p20),
        metadata=decode_metadata(cbor),
        minimal_proxy_target=minimal_target,
        has_delegatecall=bool(counts.get("DELEGATECALL")),
        has_selfdestruct=bool(counts.get("SELFDESTRUCT")),
        notes=notes,
    )


def mask_immutables(code: bytes, immutable_refs: dict[str, list[dict[str, int]]] | None) -> bytes:
    """Zero out immutable placeholders so deployed code can be compared with compiled code."""
    if not immutable_refs:
        return code
    b = bytearray(code)
    for refs in immutable_refs.values():
        for r in refs:
            start, length = int(r["start"]), int(r["length"])
            b[start : start + length] = b"\x00" * length
    return bytes(b)


def code_hash(code: bytes) -> str:
    return "0x" + keccak(code).hex()
